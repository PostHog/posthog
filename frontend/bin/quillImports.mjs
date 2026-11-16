import fs from 'node:fs'
import path from 'node:path'

/**
 * Per-component quill imports.
 *
 * esbuild splits code by file, and it treats every file that an index re-exports as reachable from
 * any importer of that index. So `import { Button } from '@posthog/quill'` puts every quill primitive,
 * and the Base UI component behind each one, on the page that wanted a button.
 *
 * This plugin rewrites each named import from a quill index into imports of the files that define
 * those names. The quill packages build one ES file per source module for this (see their
 * vite.config.ts), and the plugin reads each package's dist/index.js to find the file for a name.
 *
 * Only the esbuild production build runs it. The Vite dev server and Jest keep the index imports,
 * which resolve to the same modules.
 */

// The app also imports quill through its own re-export file, lib/ui/quill.
const UMBRELLA_SPECIFIERS = ['@posthog/quill', 'lib/ui/quill', '~/lib/ui/quill']
const PACKAGES = {
    '@posthog/quill-primitives': 'primitives',
    '@posthog/quill-components': 'components',
}

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')

const INDEX_IMPORT = /^import\s*\{([^}]*)\}\s*from\s*"([^"]+)";?$/
const INDEX_EXPORT = /^export\s*\{([^}]*)\}(?:\s*from\s*"([^"]+)")?;?$/
const isQuillFile = (specifier) => specifier.startsWith('.')

/**
 * Reads a rollup-built index of re-exports. Returns a map from each export name to the file that
 * defines it and the name it has in that file.
 *
 * A name that the index re-exports from another package has no quill file. It is not in the map, so
 * its imports stay on the index.
 */
export function quillExportMap(indexSource, distDir) {
    const localBindings = new Map()
    const fromOtherPackages = new Set()
    const exports = new Map()
    const bindings = (list) =>
        list
            .split(',')
            .map((part) => part.trim().split(/\s+as\s+/))
            .filter(([name]) => name)
    for (const line of indexSource.split('\n').map((text) => text.trim())) {
        if (!line || line.startsWith('/*')) {
            continue
        }
        const importMatch = INDEX_IMPORT.exec(line)
        if (importMatch) {
            const [, list, file] = importMatch
            for (const [imported, local] of bindings(list)) {
                if (isQuillFile(file)) {
                    localBindings.set(local ?? imported, { file: path.join(distDir, file), imported })
                } else {
                    fromOtherPackages.add(local ?? imported)
                }
            }
            continue
        }
        const exportMatch = INDEX_EXPORT.exec(line)
        if (!exportMatch) {
            // A name read from a half-understood index would silently stay on the index and ship with every primitive.
            throw new Error(`quill-imports: cannot read this line of a quill index: ${line}`)
        }
        const [, list, file] = exportMatch
        for (const [name, exported] of bindings(list)) {
            if (file ? !isQuillFile(file) : fromOtherPackages.has(name)) {
                continue
            }
            const target = file ? { file: path.join(distDir, file), imported: name } : localBindings.get(name)
            if (!target) {
                throw new Error(`quill-imports: ${name} is exported from a quill index but defined nowhere in it`)
            }
            exports.set(exported ?? name, target)
        }
    }
    return exports
}

/**
 * Rewrites the named quill imports in `source`. `maps` holds one export map per import specifier.
 * A name that no map knows, and every type import, stays on the index. Returns null when nothing changed.
 *
 * Only the imports before the first backtick are rewritten. Text after it can be inside a template
 * literal, and some files hold source code there that they ship to users as text.
 */
export function rewriteQuillImports(source, maps) {
    const specifiers = [...maps.keys()].map(escapeRegExp).join('|')
    const namedImport = new RegExp(
        `^([ \\t]*)import\\s+(type\\s+)?\\{([^}]*)\\}\\s*from\\s*(['"])(${specifiers})\\4;?`,
        'gm'
    )
    const firstBacktick = source.indexOf('`')
    let changed = false
    const contents = source.replace(namedImport, (statement, indent, typeOnly, list, _quote, specifier, offset) => {
        const canBeInTemplateLiteral = firstBacktick !== -1 && offset > firstBacktick
        // A comment in the list would swallow the rest of the one-line statement we emit.
        if (typeOnly || canBeInTemplateLiteral || /\/[/*]/.test(list)) {
            return statement
        }
        const map = maps.get(specifier)
        const byFile = new Map()
        const onIndex = []
        for (const part of list.split(',')) {
            const binding = part.trim()
            if (!binding) {
                continue
            }
            const [name, local] = binding.split(/\s+as\s+/)
            const target = binding.startsWith('type ') ? undefined : map.get(name)
            if (!target) {
                onIndex.push(binding)
                continue
            }
            const names = byFile.get(target.file) ?? []
            names.push(target.imported === (local ?? name) ? target.imported : `${target.imported} as ${local ?? name}`)
            byFile.set(target.file, names)
        }
        if (byFile.size === 0) {
            return statement
        }
        changed = true
        const statements = [...byFile].map(
            ([file, names]) => `import { ${names.join(', ')} } from ${JSON.stringify(file)};`
        )
        if (onIndex.length > 0) {
            statements.push(`import { ${onIndex.join(', ')} } from '${specifier}';`)
        }
        // The same number of lines as the statement it replaces, so the source map of the file stays right.
        return `${indent}${statements.join(' ')}${'\n'.repeat(statement.split('\n').length - 1)}`
    })
    return changed ? contents : null
}

function readExportMap(repoRoot, packageDir) {
    const distDir = path.join(repoRoot, 'packages/quill/packages', packageDir, 'dist')
    const indexFile = path.join(distDir, 'index.js')
    const exports = fs.existsSync(indexFile) ? quillExportMap(fs.readFileSync(indexFile, 'utf8'), distDir) : new Map()
    if (exports.size === 0) {
        // Without the map every quill import stays on the index, and the build silently ships every primitive.
        throw new Error(
            `quill-imports: no exports found in ${indexFile}. Run \`pnpm --filter '@posthog/quill-*' build\`.`
        )
    }
    return exports
}

export function quillImportMaps(repoRoot) {
    const maps = new Map()
    for (const [specifier, packageDir] of Object.entries(PACKAGES)) {
        maps.set(specifier, readExportMap(repoRoot, packageDir))
    }
    const umbrella = new Map([...maps.get('@posthog/quill-components'), ...maps.get('@posthog/quill-primitives')])
    for (const specifier of UMBRELLA_SPECIFIERS) {
        maps.set(specifier, umbrella)
    }
    return maps
}

export function quillImportsEsbuildPlugin(repoRoot) {
    return {
        name: 'quill-imports',
        setup(build) {
            const maps = quillImportMaps(repoRoot)
            build.onLoad({ filter: /\.(tsx?|jsx?|mjs)$/ }, async (args) => {
                if (args.path.includes(`${path.sep}node_modules${path.sep}`)) {
                    return undefined
                }
                const source = await fs.promises.readFile(args.path, 'utf8')
                if (!source.includes('quill')) {
                    return undefined
                }
                const contents = rewriteQuillImports(source, maps)
                if (contents === null) {
                    return undefined
                }
                const extension = path.extname(args.path).slice(1)
                return { contents, loader: extension === 'mjs' ? 'js' : extension }
            })
        },
    }
}
