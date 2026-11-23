import { existsSync, realpathSync } from 'node:fs'
import module from 'node:module'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'

import type { StackDescription, StackProblem } from './description.js'
import { evaluateExports, type ResourceOrigin } from './evaluate.js'
import { type SchemaValidator, validateDescription, validateStructure } from './validate.js'

interface LoadStackBase {
    // Source files are recorded relative to it. Defaults to the nearest folder above the stack with
    // a `.git`, or the stack folder itself.
    root?: string
}

// Either a validator, which runs each kind's schema, or `skipSchemas: true`, which checks keys,
// references and the registry's rules only. Nothing picks the second by leaving the first out.
export type LoadStackOptions = LoadStackBase &
    ({ validator: SchemaValidator; skipSchemas?: never } | { skipSchemas: true; validator?: never })

export interface StackResult {
    description: StackDescription
    problems: StackProblem[]
    origins: Map<string, ResourceOrigin>
    // The stack's entry file, relative to the root.
    entry: string | undefined
}

const ENTRY_FILES = ['index.ts', 'index.mts', 'index.js', 'index.mjs']

export function findRoot(dir: string): string {
    let folder = resolve(dir)
    for (;;) {
        if (existsSync(join(folder, '.git'))) {
            return folder
        }
        const parent = dirname(folder)
        if (parent === folder) {
            return resolve(dir)
        }
        folder = parent
    }
}

export function relativeTo(root: string, file: string): string {
    return relative(root, file).split(sep).join('/')
}

let resolvesExtensionless = false

// Bun resolves `./events` to `./events.ts` on its own. Node needs the extension, so under Node the
// stack's own relative imports also try `.ts` and `/index.ts`, the way a bundler would.
function resolveLikeBundlers(): void {
    if (resolvesExtensionless || process.versions.bun || typeof module.registerHooks !== 'function') {
        return
    }
    resolvesExtensionless = true
    module.registerHooks({
        resolve(specifier, context, nextResolve) {
            try {
                return nextResolve(specifier, context)
            } catch (error) {
                const fromTypeScript = context.parentURL?.endsWith('.ts') || context.parentURL?.endsWith('.mts')
                if (!fromTypeScript || !(specifier.startsWith('./') || specifier.startsWith('../'))) {
                    throw error
                }
                for (const candidate of [
                    `${specifier}.ts`,
                    `${specifier}/index.ts`,
                    specifier.replace(/\.js$/, '.ts'),
                ]) {
                    try {
                        return nextResolve(candidate, context)
                    } catch {
                        // Try the next form.
                    }
                }
                throw error
            }
        },
    })
}

const FRAME = /\(?((?:file:\/\/)?(?:\/|[A-Za-z]:[\\/])[^()]*?):(\d+):\d+\)?\s*$/

// Where in the stack folder an evaluation error was thrown, from the first frame inside it.
function thrownAt(error: unknown, dir: string): { file: string; line: number } | undefined {
    const stack = error instanceof Error ? (error.stack ?? '') : ''
    for (const line of stack.split('\n')) {
        const match = FRAME.exec(line.trim())
        if (!match?.[1] || !match[2]) {
            continue
        }
        const file = match[1].startsWith('file://') ? decodeURIComponent(new URL(match[1]).pathname) : match[1]
        if (file.startsWith(dir + sep) && !file.includes(`${sep}node_modules${sep}`)) {
            return { file, line: Number(match[2]) }
        }
    }
    return undefined
}

function compareProblems(a: StackProblem, b: StackProblem): number {
    const fields = [
        [a.file ?? '', b.file ?? ''],
        [a.kind ?? '', b.kind ?? ''],
        [a.key ?? '', b.key ?? ''],
        [a.path ?? '', b.path ?? ''],
        [a.code, b.code],
        [a.message, b.message],
    ] as const
    for (const [left, right] of fields) {
        if (left !== right) {
            return left < right ? -1 : 1
        }
    }
    return (a.line ?? 0) - (b.line ?? 0)
}

export function sortProblems(problems: StackProblem[]): StackProblem[] {
    return [...problems].sort(compareProblems)
}

// Imports the stack folder's index, evaluates every export into the description, and validates it.
// Evaluation problems come back as problems; nothing here throws for a broken folder.
//
// The folder's modules are imported into this process, and a module is evaluated once per process.
// A second call in the same process after the files changed returns the first evaluation, so a
// caller that watches files runs each check in a fresh process, as `hog check` does.
export async function loadStack(dir: string, options: LoadStackOptions): Promise<StackResult> {
    // Real paths, because the module loader reports files by their real path, as on macOS, where
    // the temporary folder is a link.
    const real = (path: string): string => (existsSync(path) ? realpathSync(path) : path)
    const folder = real(resolve(dir))
    const root = real(resolve(options.root ?? findRoot(folder)))
    const empty: StackDescription = { version: 1, resources: [] }
    const entry = ENTRY_FILES.map((name) => join(folder, name)).find((file) => existsSync(file))
    if (!entry) {
        return {
            description: empty,
            problems: [
                {
                    code: 'entry_missing',
                    severity: 'error',
                    file: relativeTo(root, folder),
                    message: `${relativeTo(root, folder) || '.'} has no index.ts. A stack folder exports its definitions from index.ts.`,
                },
            ],
            origins: new Map(),
            entry: undefined,
        }
    }
    resolveLikeBundlers()
    let exports: Record<string, unknown>
    try {
        exports = (await import(pathToFileURL(entry).href)) as Record<string, unknown>
    } catch (error) {
        const at = thrownAt(error, folder)
        const reason = error instanceof Error ? error.message : String(error)
        return {
            description: empty,
            problems: [
                {
                    code: 'evaluation_failed',
                    severity: 'error',
                    file: relativeTo(root, at?.file ?? entry),
                    ...(at ? { line: at.line } : {}),
                    message: `Evaluating the stack failed: ${reason}`,
                },
            ],
            origins: new Map(),
            entry: relativeTo(root, entry),
        }
    }
    const evaluation = evaluateExports(exports, { root, stackDir: folder })
    const context = { origins: evaluation.origins, excluded: evaluation.excluded }
    const problems = [
        ...evaluation.problems,
        ...(options.validator
            ? validateDescription(evaluation.description, { ...context, validator: options.validator })
            : validateStructure(evaluation.description, context)),
    ]
    return {
        description: evaluation.description,
        problems: sortProblems(problems),
        origins: evaluation.origins,
        entry: relativeTo(root, entry),
    }
}
