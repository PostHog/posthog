import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'

import type { StackProblem } from './description.js'
import { findRoot, relativeTo } from './load.js'

export interface TypeCheckResult {
    // `skipped` when the project has no TypeScript compiler to check with. A skipped check is not a
    // pass: `reason` says why it didn't run.
    status: 'passed' | 'failed' | 'skipped'
    reason?: string
    // The compiler's version, when one ran.
    compiler?: string
    // The tsconfig.json the compiler options came from, relative to the root.
    config?: string
    problems: StackProblem[]
}

// The part of the `typescript` module this file uses. The compiler is the project's own, found
// from the stack folder, so the SDK carries no dependency on it.
interface Diagnostic {
    file?: { fileName: string; getLineAndCharacterOfPosition(position: number): { line: number } }
    start?: number
    category: number
    code: number
    messageText: unknown
}

interface SourceFile {
    fileName: string
    statements: readonly { moduleSpecifier?: { text?: string }; getStart(file?: SourceFile): number }[]
    getLineAndCharacterOfPosition(position: number): { line: number }
}

interface Program {
    getSourceFiles(): readonly SourceFile[]
}

export interface TypeScript {
    version: string
    sys: { fileExists(path: string): boolean }
    findConfigFile(searchPath: string, fileExists: (path: string) => boolean): string | undefined
    getParsedCommandLineOfConfigFile(
        path: string,
        options: Record<string, unknown>,
        host: Record<string, unknown>
    ): { options: Record<string, unknown>; errors: Diagnostic[] } | undefined
    createProgram(options: { rootNames: string[]; options: Record<string, unknown> }): Program
    getPreEmitDiagnostics(program: Program): readonly Diagnostic[]
    flattenDiagnosticMessageText(text: unknown, newLine: string): string
    DiagnosticCategory: { Error: number }
    ModuleKind: { ESNext: number }
    ModuleResolutionKind: { Bundler: number }
    ScriptTarget: { ES2022: number }
}

const ENTRY_FILES = ['index.ts', 'index.mts']

export async function findCompiler(folder: string): Promise<TypeScript | undefined> {
    let path: string
    try {
        path = createRequire(join(folder, 'index.ts')).resolve('typescript')
    } catch {
        return undefined
    }
    try {
        const loaded = (await import(pathToFileURL(path).href)) as TypeScript & { default?: TypeScript }
        const ts = loaded.default ?? loaded
        return typeof ts.createProgram === 'function' && typeof ts.getPreEmitDiagnostics === 'function' ? ts : undefined
    } catch {
        // A broken install, such as a link to a removed folder, counts as no compiler.
        return undefined
    }
}

// Settings for a folder with no tsconfig.json above it, close to what a bundler accepts.
function defaultOptions(ts: TypeScript): Record<string, unknown> {
    return {
        strict: true,
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ESNext,
        moduleResolution: ts.ModuleResolutionKind.Bundler,
        skipLibCheck: true,
        allowImportingTsExtensions: true,
    }
}

// Type-checks the stack's index and everything it imports, with the compiler options of the
// nearest tsconfig.json, and reports errors in the project's own files.
export async function typeCheckStack(dir: string, options: { root?: string } = {}): Promise<TypeCheckResult> {
    const folder = resolve(dir)
    const root = resolve(options.root ?? findRoot(folder))
    const entry = ENTRY_FILES.map((name) => join(folder, name)).find((file) => existsSync(file))
    const ts = entry ? await findCompiler(folder) : undefined
    if (!entry || !ts) {
        return {
            status: 'skipped',
            reason: entry
                ? 'This project has no usable TypeScript compiler. Add typescript as a dev dependency to check types.'
                : 'The stack has no index.ts to check.',
            problems: [],
        }
    }
    const problems: StackProblem[] = []
    const toProblem = (diagnostic: Diagnostic): StackProblem => {
        const file = diagnostic.file
        return {
            code: 'type_error',
            severity: 'error',
            message: `TS${diagnostic.code}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')}`,
            ...(file ? { file: relativeTo(root, file.fileName) } : {}),
            ...(file && diagnostic.start !== undefined
                ? { line: file.getLineAndCharacterOfPosition(diagnostic.start).line + 1 }
                : {}),
        }
    }
    const configPath = ts.findConfigFile(folder, ts.sys.fileExists)
    let compilerOptions = defaultOptions(ts)
    if (configPath) {
        const parsed = ts.getParsedCommandLineOfConfigFile(
            configPath,
            {},
            {
                ...ts.sys,
                onUnRecoverableConfigFileDiagnostic: (diagnostic: Diagnostic) => problems.push(toProblem(diagnostic)),
            }
        )
        if (parsed) {
            compilerOptions = parsed.options
            problems.push(...parsed.errors.filter((d) => d.category === ts.DiagnosticCategory.Error).map(toProblem))
        }
    }
    // Only diagnostics are read, so nothing is emitted and the project's own emit settings stay as
    // they are. `noCheck` would turn the check into a parse, so it is forced off.
    const program = ts.createProgram({ rootNames: [entry], options: { ...compilerOptions, noCheck: false } })
    problems.push(...pathImportProblems(program, compilerOptions, root))
    const ownFile = (diagnostic: Diagnostic): boolean =>
        !diagnostic.file || !diagnostic.file.fileName.split(/[\\/]/).includes('node_modules')
    problems.push(
        ...ts
            .getPreEmitDiagnostics(program)
            .filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error && ownFile(diagnostic))
            .map(toProblem)
    )
    return {
        status: problems.some((problem) => problem.severity === 'error') ? 'failed' : 'passed',
        compiler: ts.version,
        ...(configPath ? { config: relativeTo(root, configPath.split('/').join(sep)) } : {}),
        problems,
    }
}

// Evaluation imports the folder with the runtime's resolver, which does not read tsconfig `paths`,
// so an import that only `paths` resolves would pass the type check and then fail to load.
function pathImportProblems(program: Program, options: Record<string, unknown>, root: string): StackProblem[] {
    const paths = options.paths as Record<string, unknown> | undefined
    if (!paths || Object.keys(paths).length === 0) {
        return []
    }
    const patterns = Object.keys(paths).map(
        (key) => new RegExp(`^${key.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace('*', '.*')}$`)
    )
    const problems: StackProblem[] = []
    for (const file of program.getSourceFiles()) {
        if (file.fileName.split(/[\\/]/).includes('node_modules') || file.fileName.endsWith('.d.ts')) {
            continue
        }
        for (const statement of file.statements) {
            const specifier = statement.moduleSpecifier?.text
            if (!specifier || specifier.startsWith('.') || !patterns.some((pattern) => pattern.test(specifier))) {
                continue
            }
            problems.push({
                code: 'import_unsupported',
                severity: 'error',
                file: relativeTo(root, file.fileName),
                line: file.getLineAndCharacterOfPosition(statement.getStart(file)).line + 1,
                message: `The import ${specifier} resolves only through tsconfig paths, which evaluation doesn't read. Use a relative import or a package name.`,
            })
        }
    }
    return problems
}
