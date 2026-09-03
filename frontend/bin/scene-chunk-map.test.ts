import fs from 'node:fs'
import path from 'node:path'

import {
    keyChunksBySceneId,
    parseAppSceneImports,
    parseProductSceneImports,
    parseSceneEnum,
} from './scene-chunk-map.mjs'

const SCENE_TYPES = `
export enum Scene {
    Dashboard = 'Dashboard',
    Replay = 'Replay',
    SessionAttributionExplorer = 'SessionAttributionExplorer',
}
`
const APP_SCENES = `
export const appScenes = {
    ...productScenes,
    [Scene.Dashboard]: () => import('./dashboard/Dashboard'),
    [Scene.Replay]: () => import('./session-recordings/SessionRecordings'),
    [Scene.SessionAttributionExplorer]: () =>
        import('scenes/web-analytics/SessionAttributionExplorer/SessionAttributionExplorerScene'),
    [Scene.Error404]: () => ({ default: preloadedScenes[Scene.Error404].component }),
}
`
const PRODUCT_SCENES = `
export const productScenes = {
    Actions: () => import('../../products/actions/frontend/pages/Actions'),
    AIObservabilityPlayground: () =>
        import('../../products/ai_observability/frontend/playground/AIObservabilityPlaygroundScene'),
}
`
type MetaImport = { kind: string; original?: string; path: string }
type MetaOutput = { entryPoint?: string; exports: string[]; imports: MetaImport[] }
const dyn = (original: string, resolved: string): MetaImport => ({ kind: 'dynamic-import', original, path: resolved })
const INPUTS = {
    'src/scenes/appScenes.ts': {
        imports: [
            dyn('./dashboard/Dashboard', 'src/scenes/dashboard/Dashboard.tsx'),
            dyn('./session-recordings/SessionRecordings', 'src/scenes/session-recordings/SessionRecordings.tsx'),
        ],
    },
    'src/productScenes.tsx': {
        imports: [
            dyn('../../products/actions/frontend/pages/Actions', '../products/actions/frontend/pages/Actions.tsx'),
        ],
    },
}
const entry = (entryPoint: string, exports: string[], chunkIds: string[]): MetaOutput => ({
    entryPoint,
    exports,
    imports: chunkIds.map((id) => ({ kind: 'import-statement', path: `dist/chunk-${id}.js` })),
})
const OUTPUTS = {
    'dist/index-AAAA.js': entry('src/index.tsx', [], ['I1', 'I2']),
    'dist/Dashboard-BBBB.js': entry('src/scenes/dashboard/Dashboard.tsx', ['Dashboard', 'scene'], ['D1', 'D2']),
    // Export name differs from the scene id: the old export-keyed map could never be looked up for Replay
    'dist/SessionRecordingsPageTabs-CCCC.js': entry(
        'src/scenes/session-recordings/SessionRecordings.tsx',
        ['SessionRecordingsPageTabs', 'scene'],
        ['R1']
    ),
    'dist/Actions-DDDD.js': entry('../products/actions/frontend/pages/Actions.tsx', ['Actions'], ['A1']),
    'dist/Dashboard-BBBB.css': { entryPoint: undefined, exports: [], imports: [] },
}

describe('scene chunk map', () => {
    it('keys chunks by scene id, keeps the index entry, and drops export-name keys', () => {
        const { chunks, resolved, unresolved } = keyChunksBySceneId({
            inputs: INPUTS,
            outputs: OUTPUTS,
            sceneTypesSource: SCENE_TYPES,
            appScenesSource: APP_SCENES,
            productScenesSource: PRODUCT_SCENES,
        })
        expect(chunks).toEqual({ index: ['I1', 'I2'], Dashboard: ['D1', 'D2'], Replay: ['R1'], Actions: ['A1'] })
        expect(chunks).not.toHaveProperty('SessionRecordingsPageTabs')
        expect(resolved).toBe(3)
        // Not in the metafile's dynamic-import edges, so it is reported rather than silently dropped
        expect(unresolved).toEqual(['Scene.SessionAttributionExplorer', 'AIObservabilityPlayground'])
    })

    it('still parses the real scene maps, so a format change shows up here before it silently disables prefetching', () => {
        const src = (p: string): string => fs.readFileSync(path.resolve(__dirname, '..', 'src', p), 'utf-8')
        const sceneEnum = parseSceneEnum(src('scenes/sceneTypes.ts'))
        const appScenes = parseAppSceneImports(src('scenes/appScenes.ts'))
        const productScenes = parseProductSceneImports(src('productScenes.tsx'))

        expect(appScenes.length).toBeGreaterThan(100)
        expect(productScenes.length).toBeGreaterThan(50)
        const unknownMembers = appScenes.filter(({ member }) => !sceneEnum.has(member)).map(({ member }) => member)
        expect(unknownMembers).toEqual([])
    })
})
