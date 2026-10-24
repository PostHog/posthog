import { exec, execFile } from 'child_process'
import { createHash } from 'crypto'
import { mkdir, readFile, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { HogBytecode } from '../types'
import { Semaphore } from '../utils/sempahore'

const ROOT_DIR = path.join(__dirname, '..', '..', '..', '..')
const CACHE_DIR = path.join(ROOT_DIR, 'nodejs', 'tests', 'fixtures', 'hog-bytecode')
const CACHE_REWRITE = process.env.HOG_BYTECODE_CACHE_REWRITE === '1'
const CACHE_REQUIRED = process.env.HOG_BYTECODE_CACHE_REQUIRED === 'true'

const cache = new Map<string, HogBytecode>()
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

type CompileCommand = (sourceFile: string, outputFile: string) => Promise<unknown>

const compileProgram: CompileCommand = (sourceFile, outputFile) =>
    new Promise((resolve, reject) => {
        exec(
            `cd ${ROOT_DIR} && ./bin/hoge ${sourceFile} ${outputFile}`,
            { env: { ...process.env, TEST: 'true' } },
            (error, stdout) => (error ? reject(error) : resolve(stdout))
        )
    })

const compileTemplateString: CompileCommand = (sourceFile, outputFile) =>
    new Promise((resolve, reject) => {
        execFile(
            'python3',
            ['-c', TEMPLATE_COMPILER, sourceFile, outputFile],
            { cwd: ROOT_DIR, env: { ...process.env, TEST: 'true' } },
            (error, stdout) => (error ? reject(error) : resolve(stdout))
        )
    })

export async function compileHog(hog: string): Promise<HogBytecode> {
    return compileCached(hog, hog, compileProgram)
}

/** Compiles a templated input value such as `Hello {person.name}` the way the Django app stores it. */
export async function compileHogTemplate(template: string): Promise<HogBytecode> {
    return compileCached(`template:${template}`, template, compileTemplateString)
}

async function compileCached(cacheKey: string, source: string, compile: CompileCommand): Promise<HogBytecode> {
    return semaphore.run(async () => {
        const cached = cache.get(cacheKey)
        if (cached) {
            return cached
        }

        const file = cacheFile(cacheKey)
        let cacheMiss = false
        if (!CACHE_REWRITE) {
            try {
                const bytecode = parseJSON(await readFile(file, 'utf-8')) as HogBytecode
                cache.set(cacheKey, bytecode)
                return bytecode
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

        const output = parseJSON(await readFile(outputFile, 'utf-8'))

        cache.set(cacheKey, output)
        if (CACHE_REWRITE || cacheMiss) {
            await mkdir(CACHE_DIR, { recursive: true })
            await writeFile(file, JSON.stringify(output) + '\n')
        }

        return output
    })
}
