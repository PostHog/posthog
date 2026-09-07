// Keys the esbuild chunk map by scene id.
//
// `sceneLogic` asks the chunk loader for `ESBUILD_LOAD_CHUNKS(sceneId)` before it imports a scene,
// so the browser can fetch every chunk of the scene in parallel instead of discovering them level
// by level. esbuild only knows output files, so the raw map (`getChunks` in @posthog/esbuilder) is
// keyed by each entry's first export name. That matches the scene id by coincidence
// (`Dashboard`, `ProjectHomepage`) and misses everything else (`Replay`, `WebAnalytics`, ...).
//
// This module resolves the real mapping: scene id -> lazy import specifier (from the scene maps in
// source) -> resolved module (from the metafile's dynamic-import edges, which record the original
// specifier) -> entry output -> its chunk list.

const APP_SCENES_INPUT = 'src/scenes/appScenes.ts'
const PRODUCT_SCENES_INPUT = 'src/productScenes.tsx'
const INDEX_ENTRY = 'src/index.tsx'

/** `export enum Scene { Dashboard = 'Dashboard', ... }` -> Map(member -> id). */
export function parseSceneEnum(sceneTypesSource) {
    const body = sceneTypesSource.match(/export enum Scene\s*\{([\s\S]*?)\n\}/)?.[1] ?? ''
    const members = new Map()
    for (const [, member, id] of body.matchAll(/^\s*(\w+)\s*=\s*'([^']+)'/gm)) {
        members.set(member, id)
    }
    return members
}

/** `[Scene.Dashboard]: () => import('./dashboard/Dashboard')` -> [{ member, specifier }]. */
export function parseAppSceneImports(appScenesSource) {
    return [...appScenesSource.matchAll(/\[Scene\.(\w+)\]:\s*\(\)\s*=>\s*import\('([^']+)'\)/g)].map(
        ([, member, specifier]) => ({ member, specifier })
    )
}

/** `Actions: () => import('../../products/actions/frontend/pages/Actions')` -> [{ id, specifier }]. */
export function parseProductSceneImports(productScenesSource) {
    return [...productScenesSource.matchAll(/^\s*(\w+):\s*\(\)\s*=>\s*import\('([^']+)'\)/gm)].map(
        ([, id, specifier]) => ({ id, specifier })
    )
}

function chunkIdsOf(output) {
    return (output.imports || [])
        .filter((i) => i.kind === 'import-statement' && i.path.startsWith('dist/chunk-'))
        .map((i) => i.path.replace('dist/chunk-', '').replace('.js', ''))
}

/**
 * Build the chunk map keyed by scene id (plus `index` for the boot entry).
 *
 * `inputs`/`outputs` are the esbuild metafile. Scenes whose import cannot be followed through
 * the metafile are returned in `unresolved` so the build can report them: a missing scene only
 * loses the parallel prefetch, the scene still loads through `import()`.
 */
export function keyChunksBySceneId({ inputs, outputs, sceneTypesSource, appScenesSource, productScenesSource }) {
    const sceneEnum = parseSceneEnum(sceneTypesSource)

    const specifierToModule = new Map()
    for (const input of [APP_SCENES_INPUT, PRODUCT_SCENES_INPUT]) {
        for (const imp of inputs[input]?.imports || []) {
            if (imp.kind === 'dynamic-import' && imp.original) {
                specifierToModule.set(`${input}:${imp.original}`, imp.path)
            }
        }
    }

    const entryOutputByModule = new Map()
    for (const [outputPath, output] of Object.entries(outputs)) {
        if (output.entryPoint && outputPath.endsWith('.js')) {
            entryOutputByModule.set(output.entryPoint, output)
        }
    }

    const chunks = {}
    const unresolved = []
    const indexOutput = entryOutputByModule.get(INDEX_ENTRY)
    if (indexOutput) {
        chunks.index = chunkIdsOf(indexOutput)
    }

    const scenes = [
        ...parseAppSceneImports(appScenesSource).map(({ member, specifier }) => ({
            id: sceneEnum.get(member),
            label: `Scene.${member}`,
            key: `${APP_SCENES_INPUT}:${specifier}`,
        })),
        ...parseProductSceneImports(productScenesSource).map(({ id, specifier }) => ({
            id,
            label: id,
            key: `${PRODUCT_SCENES_INPUT}:${specifier}`,
        })),
    ]
    for (const { id, label, key } of scenes) {
        const output = id && entryOutputByModule.get(specifierToModule.get(key))
        if (!output) {
            unresolved.push(label)
            continue
        }
        const ids = chunkIdsOf(output)
        if (ids.length > 0) {
            chunks[id] = ids
        }
    }

    return { chunks, resolved: scenes.length - unresolved.length, unresolved }
}
