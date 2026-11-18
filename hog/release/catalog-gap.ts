// Whether a pull request changes code compiled into hog that the downloadable tool catalog can't deliver.
// The compiled files come from the build metafiles. Run with --base <commit>; prints the result as JSON.

import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { posix, relative, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import { parseJsonOrUndefined } from '../src/core/json'

export const CATALOG_TOOLS_JSON = 'services/mcp/schema/cli-catalog-tools.json'
export const CATALOG_SCHEMA = 'services/mcp/src/cli/catalog/schema.ts'
const WORKFLOW = '.github/workflows/ci-hog-changeset.yml'
const GENERATED_TOOLS_DIR = 'services/mcp/src/tools/generated/'
// Generated, but code rather than catalog data: the barrel, the hook registry and the query wrappers.
const GENERATED_CODE = new Set(['index.ts', 'hooks.ts', 'query-wrappers.ts'])
const DEFINITION_FILES = new Set([
    'services/mcp/schema/tool-definitions.json',
    'services/mcp/schema/generated-tool-definitions.json',
])

export interface Reason {
    file: string
    why: string
}

export interface GapResult {
    needsRelease: boolean
    bump: 'patch' | 'minor'
    reasons: Reason[]
}

export interface GapInput {
    changed: string[]
    compiled: Set<string>
    readBase: (path: string) => string | undefined
    readHead: (path: string) => string | undefined
}

const JsonObject = z.record(z.string(), z.unknown())
const Metafile = z.object({ inputs: z.record(z.string(), z.unknown()) })
const Workflow = z.object({ on: z.object({ pull_request: z.object({ paths: z.array(z.string()) }) }) })

function jsonObject(text: string | undefined): Record<string, unknown> {
    return (text && parseJsonOrUndefined(text, JsonObject)) || {}
}

function generatedToolNames(source: string | undefined): string[] {
    const map = source?.split('export const GENERATED_TOOLS')[1] ?? ''
    return [...map.matchAll(/^\s+'([a-z0-9-]+)':/gm)].map((match) => match[1]!)
}

function catalogTools(input: GapInput): Set<string> {
    const text = input.readHead(CATALOG_TOOLS_JSON)
    return new Set(Object.keys(jsonObject(text)))
}

function changedKeys(base: string | undefined, head: string | undefined): string[] {
    const before = jsonObject(base)
    const after = jsonObject(head)
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
        (key) => JSON.stringify(before[key]) !== JSON.stringify(after[key])
    )
}

function schemaVersion(source: string | undefined): string | undefined {
    return source?.match(/export const CATALOG_SCHEMA_VERSION = (\d+)/)?.[1]
}

// Anything compiled into hog counts unless the catalog provably carries it.
export function findCatalogGaps(input: GapInput): GapResult {
    const carried = catalogTools(input)
    const reasons: Reason[] = []

    for (const file of input.changed) {
        if (!input.compiled.has(file) || file === CATALOG_TOOLS_JSON) {
            continue
        }

        const name = file.startsWith(GENERATED_TOOLS_DIR) ? file.slice(GENERATED_TOOLS_DIR.length) : undefined
        if (name && !name.includes('/') && !GENERATED_CODE.has(name)) {
            const tools = [...generatedToolNames(input.readBase(file)), ...generatedToolNames(input.readHead(file))]
            const missing = tools.filter((tool) => !carried.has(tool))
            if (tools.length > 0 && missing.length === 0) {
                continue
            }
            reasons.push({
                file,
                why: `generated tools the catalog doesn't carry: ${missing.join(', ') || 'none found'}`,
            })
            continue
        }

        if (DEFINITION_FILES.has(file)) {
            const keys = changedKeys(input.readBase(file), input.readHead(file))
            const missing = keys.filter((key) => !carried.has(key))
            if (missing.length === 0) {
                continue
            }
            reasons.push({ file, why: `definitions of tools the catalog doesn't carry: ${missing.join(', ')}` })
            continue
        }

        reasons.push({ file, why: 'compiled into hog' })
    }

    const formatChanged =
        schemaVersion(input.readBase(CATALOG_SCHEMA)) !== schemaVersion(input.readHead(CATALOG_SCHEMA))
    if (formatChanged && !reasons.some((reason) => reason.file === CATALOG_SCHEMA)) {
        reasons.push({ file: CATALOG_SCHEMA, why: 'the catalog format version changed' })
    }

    return { needsRelease: reasons.length > 0, bump: formatChanged ? 'minor' : 'patch', reasons }
}

export function compiledFiles(metafiles: { path: string; root: string }[], repoRoot: string): Set<string> {
    const files = new Set<string>()
    for (const { path, root } of metafiles) {
        const inputs = parseJsonOrUndefined(readFileSync(path, 'utf8'), Metafile)?.inputs ?? {}
        for (const input of Object.keys(inputs)) {
            const file = relative(repoRoot, resolve(root, input)).split('\\').join(posix.sep)
            if (!file.startsWith('..') && !file.includes('node_modules/') && !file.startsWith('services/mcp/dist/')) {
                files.add(file)
            }
        }
    }
    return files
}

// Patterns apply in order, and a later `!pattern` excludes again, as GitHub applies them.
export function untriggeredFiles(compiled: Set<string>, workflow: string): string[] {
    const patterns = Workflow.parse(parseYaml(workflow)).on.pull_request.paths
    return [...compiled].filter(
        (file) =>
            !patterns.reduce((matched, pattern) => {
                const negated = pattern.startsWith('!')
                return new Bun.Glob(negated ? pattern.slice(1) : pattern).match(file) ? !negated : matched
            }, false)
    )
}

// Generated schema files are larger than execFileSync's default 1 MiB output buffer.
const GIT_OUTPUT_LIMIT = 512 * 1024 * 1024

// Only a path the commit lacks reads as missing. Any other git failure throws, so it can't hide a change.
export function readAt(repoRoot: string): (ref: string) => (path: string) => string | undefined {
    return (ref) => (path) =>
        git(repoRoot, 'ls-tree', ref, '--', path).trim() ? git(repoRoot, 'show', `${ref}:${path}`) : undefined
}

function git(repoRoot: string, ...args: string[]): string {
    return execFileSync('git', args, {
        cwd: repoRoot,
        encoding: 'utf8',
        maxBuffer: GIT_OUTPUT_LIMIT,
        stdio: ['ignore', 'pipe', 'pipe'],
    })
}

if (import.meta.main) {
    const repoRoot = resolve(import.meta.dir, '../..')
    const { values } = parseArgs({
        options: {
            base: { type: 'string' },
            'hog-metafile': { type: 'string', default: resolve(repoRoot, 'hog/dist/hog.metafile.json') },
            'mcp-metafile': {
                type: 'string',
                multiple: true,
                default: [
                    resolve(repoRoot, 'services/mcp/dist/cli-library.metafile.json'),
                    resolve(repoRoot, 'services/mcp/dist/cli-skills.metafile.json'),
                ],
            },
        },
    })
    if (!values.base) {
        console.error('Pass the commit the pull request branches from with --base.')
        process.exit(1)
    }

    const metafiles = [
        { path: values['hog-metafile'], root: resolve(repoRoot, 'hog') },
        ...values['mcp-metafile'].map((path) => ({ path, root: resolve(repoRoot, 'services/mcp') })),
    ]
    for (const { path } of metafiles) {
        if (!existsSync(path)) {
            console.error(`Missing ${path}. Build hog and the CLI library first.`)
            process.exit(1)
        }
    }

    const read = readAt(repoRoot)
    const compiled = compiledFiles(metafiles, repoRoot)
    const result = findCatalogGaps({
        changed: git(repoRoot, 'diff', '--name-only', `${values.base}...HEAD`).split('\n').filter(Boolean),
        compiled,
        readBase: read(values.base),
        readHead: read('HEAD'),
    })
    const untriggered = untriggeredFiles(compiled, readFileSync(resolve(repoRoot, WORKFLOW), 'utf8'))
    process.stdout.write(`${JSON.stringify({ ...result, untriggered })}\n`)
}
