import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'

import { createSceneManifest, keyChunksBySceneId, sceneImportsSource } from './scene-chunk-map.mjs'

type MetaImport = { kind: string; original?: string; path: string }
type MetaOutput = { entryPoint?: string; exports: string[]; imports: MetaImport[] }
const dyn = (original: string, resolved: string): MetaImport => ({ kind: 'dynamic-import', original, path: resolved })
const SCENE_MODULES = {
    Dashboard: './scenes/dashboard/Dashboard',
    Replay: './scenes/session-recordings/SessionRecordings',
    ReplayAlias: './scenes/session-recordings/SessionRecordings',
    Actions: '../../products/actions/frontend/pages/Actions',
    Standalone: './scenes/Standalone',
}
const INPUTS = {
    'src/lazySceneImports.ts': {
        imports: Object.values(SCENE_MODULES).map((specifier) => dyn(specifier, specifier + '.tsx')),
    },
}
const entry = (entryPoint: string, exports: string[], chunkIds: string[]): MetaOutput => ({
    entryPoint,
    exports,
    imports: chunkIds.map((id) => ({ kind: 'import-statement', path: `dist/chunk-${id}.js` })),
})
const OUTPUTS = {
    'dist/index-AAAA.js': entry('src/index.tsx', [], ['I1', 'I2']),
    'dist/Dashboard-BBBB.js': entry(SCENE_MODULES.Dashboard + '.tsx', ['Dashboard', 'scene'], ['D1', 'D2']),
    // Export name differs from the scene id: the old export-keyed map could never be looked up for Replay
    'dist/SessionRecordingsPageTabs-CCCC.js': entry(
        SCENE_MODULES.Replay + '.tsx',
        ['SessionRecordingsPageTabs', 'scene'],
        ['R1']
    ),
    'dist/Actions-DDDD.js': entry(SCENE_MODULES.Actions + '.tsx', ['Actions'], ['A1']),
    'dist/Standalone-EEEE.js': entry(SCENE_MODULES.Standalone + '.tsx', ['scene'], []),
    'dist/Dashboard-BBBB.css': { entryPoint: undefined, exports: [], imports: [] },
}

describe('scene chunk map', () => {
    it.each(['./scenes/replay', './scenes/other'])('rejects a duplicate scene id with path %s', (specifier) => {
        expect(() =>
            createSceneManifest([
                ['Replay', './scenes/replay'],
                ['Replay', specifier],
            ])
        ).toThrow('Duplicate scene Replay')
    })

    it('covers every manifest id, including aliases and scenes with no shared chunks', () => {
        const chunks = keyChunksBySceneId({ inputs: INPUTS, outputs: OUTPUTS, sceneModules: SCENE_MODULES })
        expect(chunks).toEqual({
            index: ['I1', 'I2'],
            Dashboard: ['D1', 'D2'],
            Replay: ['R1'],
            ReplayAlias: ['R1'],
            Actions: ['A1'],
            Standalone: [],
        })
        expect(chunks).not.toHaveProperty('SessionRecordingsPageTabs')
    })

    it.each([
        ['missing import', {}, OUTPUTS, SCENE_MODULES, 'Dashboard'],
        [
            'missing scene output',
            INPUTS,
            { 'dist/index-AAAA.js': OUTPUTS['dist/index-AAAA.js'] },
            SCENE_MODULES,
            'Dashboard',
        ],
        ['missing boot output', INPUTS, {}, SCENE_MODULES, 'index'],
        ['empty manifest', INPUTS, OUTPUTS, {}, 'empty'],
    ])('fails the build for %s', (_name, inputs, outputs, sceneModules, message) => {
        expect(() => keyChunksBySceneId({ inputs, outputs, sceneModules })).toThrow(message)
    })

    it('builds literal imports and their complete chunk map from the same manifest', () => {
        const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'scene-manifest-'))
        const sceneModules = createSceneManifest([
            ['Replay', './scenes/replay'],
            ['ReplayAlias', './scenes/replay'],
            ['Other', "./scenes/other's-view"],
        ])
        try {
            fs.mkdirSync(path.join(dir, 'src/scenes'), { recursive: true })
            fs.writeFileSync(path.join(dir, 'src/lazySceneImports.ts'), sceneImportsSource(sceneModules))
            fs.writeFileSync(path.join(dir, 'src/sceneModules.json'), JSON.stringify(sceneModules))
            fs.writeFileSync(path.join(dir, 'src/index.tsx'), "export { lazySceneImports } from './lazySceneImports'")
            fs.writeFileSync(path.join(dir, 'src/scenes/shared.ts'), 'export const shared = { value: 1 }')
            for (const specifier of new Set(Object.values(sceneModules))) {
                fs.writeFileSync(
                    path.join(dir, 'src', specifier + '.ts'),
                    "import { shared } from './shared'; export const DifferentExportName = shared"
                )
            }
            fs.writeFileSync(
                path.join(dir, 'src/check.ts'),
                `import { lazySceneImports } from './lazySceneImports'
                lazySceneImports.Replay().then(({ DifferentExportName }) => {
                    const value: number = DifferentExportName.value
                    return value
                })
                // @ts-expect-error Only registered scene IDs are valid.
                lazySceneImports.NotRegistered()`
            )
            const typecheck = (): Buffer =>
                execFileSync(
                    path.join(path.dirname(require.resolve('@typescript/native-preview/package.json')), 'bin/tsgo'),
                    [
                        '--noEmit',
                        '--module',
                        'preserve',
                        '--moduleResolution',
                        'bundler',
                        '--resolveJsonModule',
                        '--skipLibCheck',
                        '--target',
                        'es2022',
                        'src/check.ts',
                    ],
                    { cwd: dir, stdio: 'pipe' }
                )
            typecheck()
            fs.writeFileSync(
                path.join(dir, 'src/sceneModules.json'),
                JSON.stringify({ ...sceneModules, MissingLoader: './scenes/replay' })
            )
            expect(typecheck).toThrow()
            fs.writeFileSync(path.join(dir, 'src/sceneModules.json'), JSON.stringify(sceneModules))

            const esbuild = createRequire(require.resolve('@posthog/esbuilder')).resolve('esbuild/bin/esbuild')
            execFileSync(
                esbuild,
                [
                    'src/index.tsx',
                    '--bundle',
                    '--splitting',
                    '--format=esm',
                    '--outdir=dist',
                    '--chunk-names=chunk-[hash]',
                    '--metafile=meta.json',
                    '--log-level=error',
                ],
                { cwd: dir }
            )
            const metafile = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'))
            const chunks = keyChunksBySceneId({ ...metafile, sceneModules })
            expect(Object.keys(chunks).sort()).toEqual(['index', ...Object.keys(sceneModules)].sort())
            expect(chunks.Replay.length).toBeGreaterThan(0)
            expect(chunks.ReplayAlias).toEqual(chunks.Replay)
            for (const ids of Object.values(chunks)) {
                for (const id of ids) {
                    expect(fs.existsSync(path.join(dir, `dist/chunk-${id}.js`))).toBe(true)
                }
            }
        } finally {
            fs.rmSync(dir, { recursive: true, force: true })
        }
    })
})
