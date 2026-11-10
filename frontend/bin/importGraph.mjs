// The app's static import graph, read from an esbuild metafile. check-layers.mjs and check-css-coupling.mjs share it.
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { esbuildBuild } from '@posthog/esbuilder'

import { BOOT_ENTRIES } from './bootEntries.mjs'

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

// Path aliases resolve through tsconfig; anything else that is not relative is a package, and packages
// are outside the layer map.
const ALIAS_PREFIXES = ['lib/', 'scenes/', '~/', 'products/', 'public/', '@posthog/', '@common/']
const ASSET_EXTENSIONS = [
    '.css',
    '.scss',
    '.svg',
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.avif',
    '.ico',
    '.woff',
    '.woff2',
    '.ttf',
    '.otf',
    '.eot',
    '.mp3',
    '.mp4',
    '.wav',
    '.ogg',
    '.lottie',
    '.riv',
    '.json',
    '.md',
    '.txt',
    '.html',
    '.yaml',
    '.yml',
    '.csv',
    '.wasm',
    '.bin',
    '.gz',
    '.zip',
    '.glb',
    '.gltf',
]

const externalizePackages = {
    name: 'externalize-packages',
    setup(build) {
        build.onResolve({ filter: /\?[a-z]+$/ }, (args) => ({ path: args.path, external: true }))
        build.onResolve({ filter: /^[^./]/ }, async (args) => {
            if (args.pluginData?.resolvingAlias) {
                return undefined
            }
            if (ALIAS_PREFIXES.some((prefix) => args.path.startsWith(prefix))) {
                const resolved = await build.resolve(args.path, {
                    kind: args.kind,
                    resolveDir: args.resolveDir,
                    importer: args.importer,
                    pluginData: { resolvingAlias: true },
                })
                if (!resolved.errors.length && !resolved.path.includes('/node_modules/')) {
                    return resolved
                }
            }
            return { path: args.path, external: true }
        })
    },
}

// The `empty` loader keeps asset files out of the bundle, but esbuild still records the import edge in the
// metafile. The graph keeps those edges, because the CSS coupling check needs stylesheet imports. An asset
// carries no feature code, so the layer check skips them.
export function isAssetPath(importPath) {
    return ASSET_EXTENSIONS.includes(path.extname(importPath).toLowerCase())
}

export async function readImportGraph() {
    const result = await esbuildBuild({
        absWorkingDir: repoRoot,
        entryPoints: BOOT_ENTRIES.map((entry) => `frontend/${entry}`),
        tsconfig: path.join(repoRoot, 'tsconfig.json'),
        bundle: true,
        splitting: true,
        format: 'esm',
        jsx: 'automatic',
        write: false,
        metafile: true,
        outdir: path.join(repoRoot, 'frontend', '.layer-check-out'),
        logLevel: 'silent',
        loader: Object.fromEntries(ASSET_EXTENSIONS.map((extension) => [extension, 'empty'])),
        plugins: [externalizePackages],
    })
    const files = {}
    for (const [file, input] of Object.entries(result.metafile.inputs)) {
        files[file] = {
            bytes: input.bytes,
            staticImports: input.imports.filter((i) => i.kind === 'import-statement' && !i.external).map((i) => i.path),
        }
    }
    return files
}

export function staticReach(files, root) {
    const parentOf = new Map([[root, null]])
    const queue = [root]
    while (queue.length) {
        const file = queue.shift()
        for (const target of files[file]?.staticImports ?? []) {
            if (!parentOf.has(target)) {
                parentOf.set(target, file)
                queue.push(target)
            }
        }
    }
    return parentOf
}

export function chainTo(parentOf, file) {
    const chain = []
    for (let current = file; current; current = parentOf.get(current)) {
        chain.unshift(current)
    }
    return chain
}
