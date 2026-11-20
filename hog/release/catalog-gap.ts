// Whether the commits since <base> change code compiled into hog that the downloadable tool catalog can't
// deliver. The compiled files come from the build metafiles. Run with --base <commit>, usually the last release
// tag; prints the result as JSON. --list-compiled prints only the compiled files, one per line.

import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { posix, relative, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import { parseJsonOrUndefined } from '../src/core/json'

export const CATALOG_TOOLS_JSON = 'services/mcp/schema/cli-catalog-tools.json'
export const CATALOG_SCHEMA = 'services/mcp/src/cli/catalog/schema.ts'
const RELEASE_WORKFLOW = '.github/workflows/release-hog.yml'
const RELEASE_BUILD_JOB = 'build'
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
const Workflow = z.object({
    jobs: z.record(
        z.string(),
        z.object({
            steps: z.array(
                z.object({ uses: z.string().optional(), with: z.record(z.string(), z.unknown()).optional() })
            ),
        })
    ),
})

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
            // A module a build plugin makes up, like `cf-stub:cloudflare:workers`, is no file in the repository.
            if (input.includes(':')) {
                continue
            }
            const file = relative(repoRoot, resolve(root, input)).split('\\').join(posix.sep)
            if (!file.startsWith('..') && !file.includes('node_modules/') && !file.startsWith('services/mcp/dist/')) {
                files.add(file)
            }
        }
    }
    return files
}

export function releaseCheckoutPatterns(workflow: string): string[] {
    const steps = Workflow.parse(parseYaml(workflow)).jobs[RELEASE_BUILD_JOB]?.steps ?? []
    const sparse = steps.find((step) => step.uses?.startsWith('actions/checkout@'))?.with?.['sparse-checkout']
    if (typeof sparse !== 'string') {
        throw new Error(`The ${RELEASE_BUILD_JOB} job of ${RELEASE_WORKFLOW} has no sparse checkout to check.`)
    }
    return sparse
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
}

// The patterns are git's non-cone sparse-checkout patterns, and the release build's are all anchored. A
// pattern matches a path or any folder above it, `name/` matches only folders, and the last matching pattern
// decides, so `!/*/` can drop every top-level folder that an earlier `/*` took in.
export function outsideCheckout(compiled: Set<string>, patterns: string[]): string[] {
    const rules = patterns.map((pattern) => {
        const negated = pattern.startsWith('!')
        const body = negated ? pattern.slice(1) : pattern
        if (!body.startsWith('/')) {
            throw new Error(`Only anchored sparse-checkout patterns are supported, not ${pattern}.`)
        }
        const folderOnly = body.endsWith('/')
        return { negated, folderOnly, glob: new Bun.Glob(body.slice(1, folderOnly ? -1 : undefined)) }
    })

    return [...compiled].filter((file) => {
        const parts = file.split('/')
        const folders = parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'))
        const included = rules.reduce((current, rule) => {
            const candidates = rule.folderOnly ? folders : [...folders, file]
            return candidates.some((candidate) => rule.glob.match(candidate)) ? !rule.negated : current
        }, false)
        return !included
    })
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
            'list-compiled': { type: 'boolean', default: false },
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
    if (!values.base && !values['list-compiled']) {
        console.error('Pass the commit to compare with, usually the last release tag, with --base.')
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

    const compiled = compiledFiles(metafiles, repoRoot)
    if (values['list-compiled'] || !values.base) {
        process.stdout.write(
            [...compiled]
                .sort()
                .map((file) => `${file}\n`)
                .join('')
        )
        process.exit(0)
    }

    const read = readAt(repoRoot)
    const result = findCatalogGaps({
        changed: git(repoRoot, 'diff', '--name-only', `${values.base}...HEAD`).split('\n').filter(Boolean),
        compiled,
        readBase: read(values.base),
        readHead: read('HEAD'),
    })
    const patterns = releaseCheckoutPatterns(readFileSync(resolve(repoRoot, RELEASE_WORKFLOW), 'utf8'))
    process.stdout.write(
        `${JSON.stringify({ ...result, compiled: [...compiled].sort(), outsideReleaseCheckout: outsideCheckout(compiled, patterns) })}\n`
    )
}
