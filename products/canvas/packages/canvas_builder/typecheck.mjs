import path from 'node:path'
import ts from 'typescript'

const MAX_DIAGNOSTICS = 50
const MAX_MESSAGE_LENGTH = 1000
// Messages about a value that is itself `unknown`, not about an expected type that mentions `unknown`.
const UNKNOWN_VALUE =
    /^(?:Object is of type 'unknown'|'[^']+' is of type 'unknown'|Property '[^']+' does not exist on type 'unknown'|(?:Argument of type|Type) 'unknown(?:\[\])?' is not assignable)/

// An unresolved import is `any`, so the canvas SDK and assets need no declarations, but the `ph` global does.
const PLATFORM_DECLARATIONS = `
declare const ph: any
interface Window { ph: any }
`

// Not strict: the check is there to catch props and values a library does not accept, not to grade the canvas's own types.
const COMPILER_OPTIONS = {
    jsx: ts.JsxEmit.ReactJSX,
    module: ts.ModuleKind.ESNext,
    moduleDetection: ts.ModuleDetectionKind.Force,
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

function nodeAt(node, position) {
    return (
        ts.forEachChild(node, (child) =>
            child.getStart() <= position && position < child.end ? nodeAt(child, position) : undefined
        ) ?? node
    )
}

// This program only approximates the esbuild environment (workers, assets, DOM globals), so an error counts only
// when it sits in the arguments or props of a call or element that a library declares.
function isLibraryMisuse(program, entry) {
    if (!entry.file || entry.start === undefined) {
        return false
    }
    const start = nodeAt(entry.file, entry.start)
    for (let node = start; node.parent; node = node.parent) {
        if (node !== start && ts.isFunctionLike(node)) {
            return false
        }
        const { parent } = node
        const isCall =
            (ts.isCallExpression(parent) || ts.isNewExpression(parent)) &&
            (parent.expression === node || parent.arguments?.includes(node))
        const isElement = ts.isJsxOpeningLikeElement(parent) && (parent.tagName === node || parent.attributes === node)
        if (isCall || isElement) {
            const file = program.getTypeChecker().getResolvedSignature(parent)?.declaration?.getSourceFile()
            return !!file && program.isSourceFileFromExternalLibrary(file) && !program.isSourceFileDefaultLibrary(file)
        }
    }
    return false
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
            if (UNKNOWN_VALUE.test(message) || !isLibraryMisuse(program, entry)) {
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
