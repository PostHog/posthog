import path from 'node:path'
import ts from 'typescript'

const MAX_DIAGNOSTICS = 50
const MAX_MESSAGE_LENGTH = 1000
// Messages about a value that is itself `unknown`, not about an expected type that mentions `unknown`.
const UNKNOWN_VALUE =
    /^(?:Object is of type 'unknown'|'[^']+' is of type 'unknown'|Property '[^']+' does not exist on type 'unknown'|(?:Argument of type|Type) 'unknown(?:\[\])?' is not assignable)/

// The canvas SDK and asset imports have no published types; leaving them `any` keeps the check on the libraries.
const PLATFORM_DECLARATIONS = `
declare module '@posthog/canvas-sdk'
declare module '*.css'
declare module '*.svg'
declare module '*.png'
declare module '*.jpg'
declare module '*.jpeg'
declare module '*.gif'
declare module '*.webp'
declare module '*.txt'
declare module '*?worker'
declare const ph: any
interface Window { ph: any }
`

// Not strict: the check is there to catch props and values a library does not accept, not to grade the canvas's own types.
const COMPILER_OPTIONS = {
    jsx: ts.JsxEmit.ReactJSX,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    target: ts.ScriptTarget.ES2022,
    lib: ['lib.es2022.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'],
    types: [],
    strict: false,
    noEmit: true,
    skipLibCheck: true,
    esModuleInterop: true,
    resolveJsonModule: true,
    allowArbitraryExtensions: true,
    allowImportingTsExtensions: true,
}

function typeCheck(files, resolveDir) {
    // A virtual root inside the builder directory, so bare imports resolve through its node_modules.
    const root = path.join(resolveDir, '.canvas-typecheck')
    const sources = new Map()
    for (const [file, content] of Object.entries(files)) {
        if (typeof content === 'string' && /\.(tsx?|jsx?|json)$/.test(file)) {
            sources.set(path.join(root, file), content)
        }
    }
    const checked = [...sources.keys()].filter((file) => /\.tsx?$/.test(file))
    if (checked.length === 0) {
        return []
    }
    const declarations = path.join(root, '__platform__.d.ts')
    sources.set(declarations, PLATFORM_DECLARATIONS)

    // Module resolution skips a directory it cannot see, so the virtual folders must exist for relative imports.
    const directories = new Set()
    for (const file of sources.keys()) {
        for (let dir = path.dirname(file); dir.startsWith(root); dir = path.dirname(dir)) {
            directories.add(dir)
        }
    }

    const host = ts.createCompilerHost(COMPILER_OPTIONS, true)
    const { fileExists, readFile, getSourceFile, directoryExists, realpath } = host
    host.fileExists = (file) => sources.has(file) || fileExists(file)
    host.directoryExists = (dir) => directories.has(dir) || (directoryExists?.(dir) ?? false)
    host.realpath = (file) => (sources.has(file) || directories.has(file) ? file : (realpath?.(file) ?? file))
    host.readFile = (file) => sources.get(file) ?? readFile(file)
    host.getSourceFile = (file, language, onError) =>
        sources.has(file)
            ? ts.createSourceFile(file, sources.get(file), language, true)
            : getSourceFile(file, language, onError)
    host.writeFile = () => {}

    const program = ts.createProgram({ rootNames: [...checked, declarations], options: COMPILER_OPTIONS, host })
    const diagnostics = []
    for (const file of checked) {
        for (const entry of program.getSemanticDiagnostics(program.getSourceFile(file))) {
            if (diagnostics.length >= MAX_DIAGNOSTICS) {
                return diagnostics
            }
            const message = ts.flattenDiagnosticMessageText(entry.messageText, '\n')
            // A value the canvas's own code left as `unknown` is not a library misuse, and dozens of them would bury the ones that are.
            if (UNKNOWN_VALUE.test(message)) {
                continue
            }
            const line =
                entry.file && entry.start !== undefined
                    ? entry.file.getLineAndCharacterOfPosition(entry.start).line + 1
                    : undefined
            diagnostics.push({
                severity: 'warning',
                code: 'type_error',
                message: `TS${entry.code}: ${message}`.slice(0, MAX_MESSAGE_LENGTH),
                path: path.relative(root, file),
                ...(line ? { line } : {}),
            })
        }
    }
    return diagnostics
}

let input = ''
for await (const chunk of process.stdin) {
    input += chunk
}
const { files, resolveDir } = JSON.parse(input)
process.stdout.write(JSON.stringify(typeCheck(files, resolveDir)))
