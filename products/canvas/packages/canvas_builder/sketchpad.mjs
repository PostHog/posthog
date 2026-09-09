import Babel from '@babel/standalone'
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const manifest = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url), 'utf8'))
const allowedImports = new Set([...manifest.allowedImportSpecifiers, 'react/jsx-runtime', 'react/jsx-dev-runtime'])

function decodeUnicode(value) {
    return value.replace(/\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})/g, (match, braced, plain) => {
        const point = Number.parseInt(braced || plain, 16)
        return point <= 0x10ffff ? String.fromCodePoint(point) : match
    })
}

export function compileFragment(source) {
    if (typeof source !== 'string' || Buffer.byteLength(source) > 2 * 1024 * 1024) {
        throw new Error('Fragment source exceeds the size limit.')
    }
    const guardSource = (path) => {
        if (path.node.source && !allowedImports.has(path.node.source.value)) {
            throw path.buildCodeFrameError(`"${path.node.source.value}" is not a module a fragment can import.`)
        }
    }
    const guard = () => ({
        visitor: {
            Program(path) {
                path.traverse({
                    ReferencedIdentifier(reference) {
                        if (['require', 'eval', 'Function', 'importScripts'].includes(reference.node.name)) {
                            throw reference.buildCodeFrameError(`${reference.node.name} is not allowed in a fragment.`)
                        }
                    },
                })
            },
            ImportDeclaration: guardSource,
            ExportNamedDeclaration: guardSource,
            ExportAllDeclaration: guardSource,
            Import(path) {
                throw path.buildCodeFrameError('Dynamic imports are not allowed in a fragment.')
            },
            MetaProperty(path) {
                if (path.node.meta.name === 'import') {
                    throw path.buildCodeFrameError('import.meta is not allowed in a fragment.')
                }
            },
            JSXText(path) {
                path.node.value = decodeUnicode(path.node.value)
            },
            JSXAttribute(path) {
                const value = path.node.value
                if (value?.type === 'StringLiteral') {
                    value.value = decodeUnicode(value.value)
                    value.extra = undefined
                }
            },
        },
    })
    const { code, ast } = Babel.transform(source, {
        filename: 'fragment.tsx',
        ast: true,
        comments: false,
        plugins: [guard, 'transform-export-namespace-from', ['transform-modules-commonjs', { importInterop: 'none' }]],
        presets: [
            ['react', { runtime: 'automatic' }],
            ['typescript', { isTSX: true, allExtensions: true, onlyRemoveTypeImports: true }],
        ],
    })
    const imports = new Set()
    Babel.packages.traverse.default(ast, {
        CallExpression(path) {
            if (path.node.callee.type !== 'Identifier' || path.node.callee.name !== 'require') {
                return
            }
            const [argument] = path.node.arguments
            if (
                path.node.arguments.length !== 1 ||
                argument?.type !== 'StringLiteral' ||
                !allowedImports.has(argument.value)
            ) {
                throw path.buildCodeFrameError('The fragment has an unsupported dependency.')
            }
            imports.add(argument.value)
        },
    })
    if (Buffer.byteLength(code) > 4 * 1024 * 1024) {
        throw new Error('Compiled fragment exceeds the size limit.')
    }
    return { code, imports: [...imports] }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const { project: sources } = JSON.parse(readFileSync(0, 'utf8'))
    const results = {}
    let bytes = 0
    for (const [ref, source] of Object.entries(sources)) {
        let artifact
        try {
            artifact = compileFragment(source)
        } catch (error) {
            artifact = { error: String(error.message).slice(0, 10000) }
        }
        const size = Buffer.byteLength(JSON.stringify(artifact))
        if (bytes + size > 16 * 1024 * 1024) {
            break
        }
        results[ref] = artifact
        bytes += size
    }
    process.stdout.write(JSON.stringify(results))
}
