import { exec, execFile } from 'child_process'
import { createHash } from 'crypto'
import { mkdir, readFile, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { HogBytecode, HogFunctionFilters, HogFunctionTypeType } from '../types'
import { Semaphore } from '../utils/sempahore'

const ROOT_DIR = path.join(__dirname, '..', '..', '..', '..')
const CACHE_DIR = path.join(ROOT_DIR, 'nodejs', 'tests', 'fixtures', 'hog-bytecode')
const CACHE_REWRITE = process.env.HOG_BYTECODE_CACHE_REWRITE === '1'
const CACHE_REQUIRED = process.env.HOG_BYTECODE_CACHE_REQUIRED === 'true'

const cache = new Map<string, unknown>()
const CONCURRENT_WORKERS = 10

const semaphore = new Semaphore(CONCURRENT_WORKERS)

function cacheFile(hog: string): string {
    return path.join(CACHE_DIR, `${createHash('sha256').update(hog).digest('hex')}.json`)
}

// The same parse and compile that validation.py runs on a templated input field.
const TEMPLATE_COMPILER = `
import json, sys
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_string_template
with open(sys.argv[1]) as source, open(sys.argv[2], "w") as target:
    json.dump(create_bytecode(parse_string_template(source.read())).bytecode, target)
`

const FILTERS_COMPILER = `
import json, os, sys
from contextlib import ExitStack
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
from django.db import connections
from posthog.models.team.team import Team
from products.cdp.backend.validation import HogFunctionFiltersSerializer

def messages(errors):
    if isinstance(errors, dict):
        return [message for value in errors.values() for message in messages(value)]
    if isinstance(errors, list):
        return [message for value in errors for message in messages(value)]
    return [str(errors)]

def refuse_query(*args, **kwargs):
    raise RuntimeError("compiling these filters needs the database, which the template contract tests do not provide")

with open(sys.argv[1]) as source:
    request = json.load(source)
team = Team(id=1, project_id=1, test_account_filters=[])
context = {"function_type": request["type"], "get_team": lambda: team}
serializer = HogFunctionFiltersSerializer(data=request["filters"], context=context)
with ExitStack() as stack:
    for alias in connections:
        stack.enter_context(connections[alias].execute_wrapper(refuse_query))
    valid = serializer.is_valid()
errors = "; ".join(messages(serializer.errors))
with open(sys.argv[2], "w") as target:
    json.dump(serializer.validated_data if valid else {"bytecode": None, "bytecode_error": errors}, target)
`

type CompileCommand = (sourceFile: string, outputFile: string) => Promise<unknown>

const compileProgram: CompileCommand = (sourceFile, outputFile) =>
    new Promise((resolve, reject) => {
        exec(
            `cd ${ROOT_DIR} && ./bin/hoge ${sourceFile} ${outputFile}`,
            { env: { ...process.env, TEST: 'true' } },
            (error, stdout) => (error ? reject(error) : resolve(stdout))
        )
    })

const runPython =
    (program: string): CompileCommand =>
    (sourceFile, outputFile) =>
        new Promise((resolve, reject) => {
            execFile(
                'python3',
                ['-c', program, sourceFile, outputFile],
                { cwd: ROOT_DIR, env: { ...process.env, TEST: 'true' } },
                (error, stdout) => (error ? reject(error) : resolve(stdout))
            )
        })

export async function compileHog(hog: string): Promise<HogBytecode> {
    return compileCached<HogBytecode>(hog, hog, compileProgram)
}

/** Compiles a templated input value such as `Hello {person.name}` the way the Django app stores it. */
export async function compileHogTemplate(template: string): Promise<HogBytecode> {
    return compileCached<HogBytecode>(`template:${template}`, template, runPython(TEMPLATE_COMPILER))
}

/** Compiles filters the way the Django app does when it saves a function of the given type. */
export async function compileHogFilters(
    filters: HogFunctionFilters,
    type: HogFunctionTypeType
): Promise<HogFunctionFilters> {
    const request = JSON.stringify({ type, filters })
    return compileCached<HogFunctionFilters>(`filters:${request}`, request, runPython(FILTERS_COMPILER))
}

async function compileCached<T>(cacheKey: string, source: string, compile: CompileCommand): Promise<T> {
    return semaphore.run(async () => {
        const cached = cache.get(cacheKey)
        if (cached) {
            return cached as T
        }

        const file = cacheFile(cacheKey)
        let cacheMiss = false
        if (!CACHE_REWRITE) {
            try {
                const output = parseJSON(await readFile(file, 'utf-8')) as T
                cache.set(cacheKey, output)
                return output
            } catch (error) {
                if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
                    throw error
                }
                cacheMiss = true
            }
        }

        if (CACHE_REQUIRED) {
            throw new Error(
                `Missing compiled Hog bytecode fixture: ${file}. Run this test file locally and commit the generated fixture.`
            )
        }

        // We invoke the ./bin/hog from the root of the directory like bin/hoge <file.hog> [output.hoge]
        // We need to write and read from a temp file
        const uuid = new UUIDT().toString()
        const tempFile = path.join(tmpdir(), `hog-${uuid}.hog`)
        await writeFile(tempFile, source)

        const outputFile = path.join(tmpdir(), `hog-${uuid}.hoge`)
        try {
            await compile(tempFile, outputFile)
        } catch (error) {
            console.error('Failed to compile hog:', source)
            throw error
        }

        const output = parseJSON(await readFile(outputFile, 'utf-8')) as T

        cache.set(cacheKey, output)
        if (CACHE_REWRITE || cacheMiss) {
            await mkdir(CACHE_DIR, { recursive: true })
            await writeFile(file, JSON.stringify(output) + '\n')
        }

        return output
    })
}
