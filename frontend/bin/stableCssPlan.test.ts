import { CSS_LOAD_GLOBAL } from '@posthog/esbuilder/cssLoader.mjs'

import { cssPrelude, planCssGroups } from './stableCssPlan.mjs'

const imports = (...paths: string[]): { imports: { path: string; kind: string }[] } => ({
    imports: paths.map((path) => ({ path, kind: 'import-statement' })),
})

// A boot chain that imports Tailwind, the global styles and a button stylesheet, and one lazy scene
// that imports its own stylesheet and a shared chunk with a stylesheet of its own.
const METAFILE = {
    inputs: {
        'src/index.tsx': imports('../common/tailwind/tailwind.css', 'src/styles/global.scss'),
        'src/scenes/App.tsx': imports('src/lib/Button.scss'),
        'src/scenes/Scene.tsx': imports('src/lib/Shared.tsx', 'src/scenes/Scene.scss'),
        'src/lib/Shared.tsx': imports('src/lib/Shared.scss'),
        '../common/tailwind/tailwind.css': imports(),
        'src/styles/global.scss': imports(),
        'src/lib/Button.scss': imports(),
        'src/lib/Shared.scss': imports(),
        'src/scenes/Scene.scss': imports(),
    },
    outputs: {
        'dist/index-A.js': {
            entryPoint: 'src/index.tsx',
            cssBundle: 'dist/index-A.css',
            inputs: { 'src/index.tsx': {} },
        },
        'dist/index-A.css': {
            inputs: {
                '../common/tailwind/tailwind.css': {},
                'src/styles/global.scss': {},
                'src/lib/Button.scss': {},
                'src/lib/Shared.scss': {},
                'src/scenes/Scene.scss': {},
            },
        },
        'dist/App-B.js': { entryPoint: 'src/scenes/App.tsx', inputs: { 'src/scenes/App.tsx': {} } },
        'dist/Scene-C.js': {
            entryPoint: 'src/scenes/Scene.tsx',
            inputs: { 'src/scenes/Scene.tsx': {} },
            imports: [{ path: 'dist/chunk-D.js', kind: 'import-statement' }],
        },
        'dist/chunk-D.js': { inputs: { 'src/lib/Shared.tsx': {} } },
    },
}

describe('planCssGroups', () => {
    it('links the boot chain CSS as ordered eager layers', () => {
        const { groups, eager } = planCssGroups(METAFILE)

        expect(eager.map((name: string) => groups.get(name))).toEqual([
            ['../common/tailwind/tailwind.css'],
            ['src/styles/global.scss'],
            ['src/lib/Button.scss'],
        ])
    })

    // A scene that did not wait for its shared chunk's stylesheet would render part of itself unstyled.
    it('makes a lazy entry wait for the CSS of the shared chunks it imports, in rule order', () => {
        const { groups, lazyGroupsByEntry } = planCssGroups(METAFILE)

        expect(lazyGroupsByEntry.get('dist/Scene-C.js').map((name: string) => groups.get(name))).toEqual([
            ['src/lib/Shared.scss'],
            ['src/scenes/Scene.scss'],
        ])
        expect(lazyGroupsByEntry.has('dist/App-B.js')).toBe(false)
    })

    it('fails rather than reorder rules when boot stylesheets are out of layer order', () => {
        const outOfOrder = {
            ...METAFILE,
            outputs: {
                ...METAFILE.outputs,
                'dist/index-A.css': {
                    inputs: {
                        'src/styles/global.scss': {},
                        '../common/tailwind/tailwind.css': {},
                        'src/lib/Button.scss': {},
                    },
                },
            },
        }

        expect(() => planCssGroups(outOfOrder)).toThrow('boot stylesheets are not in layer order')
    })

    // A lazy chunk needs an eager layer to define window.ESBUILD_LOAD_CSS before its prelude can call it.
    it('fails rather than ship a lazy prelude with no eager loader to call', () => {
        const noEagerCss = {
            inputs: {
                'src/index.tsx': imports(),
                'src/scenes/App.tsx': imports(),
                'src/scenes/Scene.tsx': imports('src/scenes/Scene.scss'),
                'src/scenes/Scene.scss': imports(),
            },
            outputs: {
                'dist/index-A.js': {
                    entryPoint: 'src/index.tsx',
                    cssBundle: 'dist/index-A.css',
                    inputs: { 'src/index.tsx': {} },
                },
                'dist/index-A.css': { inputs: { 'src/scenes/Scene.scss': {} } },
                'dist/App-B.js': { entryPoint: 'src/scenes/App.tsx', inputs: { 'src/scenes/App.tsx': {} } },
                'dist/Scene-C.js': { entryPoint: 'src/scenes/Scene.tsx', inputs: { 'src/scenes/Scene.tsx': {} } },
            },
        }

        expect(() => planCssGroups(noEagerCss)).toThrow('no eager layer would define the loader')
    })

    // Merging the scene's two stylesheets would move Shared.scss's rules ahead of the second one.
    it('keeps same-owner stylesheets separate when another group sits between them', () => {
        const interleaved = {
            inputs: {
                ...METAFILE.inputs,
                'src/scenes/Scene.tsx': imports(
                    'src/lib/Shared.tsx',
                    'src/scenes/Scene.scss',
                    'src/scenes/SceneExtra.scss'
                ),
                'src/scenes/SceneExtra.scss': imports(),
            },
            outputs: {
                ...METAFILE.outputs,
                'dist/index-A.css': {
                    inputs: {
                        '../common/tailwind/tailwind.css': {},
                        'src/styles/global.scss': {},
                        'src/lib/Button.scss': {},
                        'src/scenes/Scene.scss': {},
                        'src/lib/Shared.scss': {},
                        'src/scenes/SceneExtra.scss': {},
                    },
                },
            },
        }
        const { groups, lazyGroupsByEntry, rankOfGroup } = planCssGroups(interleaved)

        expect(lazyGroupsByEntry.get('dist/Scene-C.js').map((name: string) => groups.get(name))).toEqual([
            ['src/scenes/Scene.scss'],
            ['src/lib/Shared.scss'],
            ['src/scenes/SceneExtra.scss'],
        ])
        // Ranks follow the entry stylesheet's order, so the loader can place a lazy group among others
        // whatever order scenes load them in, even though another chunk's group (Shared.scss) sits
        // between this chunk's own two groups (Scene.scss and SceneExtra.scss).
        const [sceneGroup, sharedGroup, extraGroup] = lazyGroupsByEntry.get('dist/Scene-C.js')
        expect([rankOfGroup.get(sceneGroup), rankOfGroup.get(sharedGroup), rankOfGroup.get(extraGroup)]).toEqual([
            3, 4, 5,
        ])
    })
})

describe('cssPrelude', () => {
    // A prelude that resolved a wrong URL, dropped a rank, or swapped the ternary branches would
    // still pass planCssGroups' own tests, since those never evaluate the generated string.
    async function runPrelude(
        groupNames: string[],
        rankOfGroup: Map<string, number>,
        {
            hasImportMetaResolve = true,
            loadCss,
        }: { hasImportMetaResolve?: boolean; loadCss: (entries: unknown) => Promise<boolean> }
    ): Promise<{ error?: Error }> {
        const win: Record<string, unknown> = { [CSS_LOAD_GLOBAL]: loadCss }
        const importMeta = hasImportMetaResolve ? { resolve: (specifier: string) => `resolved:${specifier}` } : {}
        // `import.meta` is only valid inside a module, so a plain Function body can't reference it
        // directly: stub it in as a parameter instead. In production this prelude runs inside an
        // ES module chunk, loaded via dynamic import, which a plain Function body can't replicate.
        const body = cssPrelude(groupNames, rankOfGroup).replace(/import\.meta/g, 'importMeta')
        try {
            await new Function('window', 'importMeta', `return (async () => { ${body} })()`)(win, importMeta)
            return {}
        } catch (error) {
            return { error: error as Error }
        }
    }

    it('resolves each group to its import-map URL and rank, in the order given', async () => {
        const rankOfGroup = new Map([
            ['lazy-a', 3],
            ['lazy-b', 1],
        ])
        let seenEntries: unknown
        await runPrelude(['lazy-a', 'lazy-b'], rankOfGroup, {
            loadCss: (entries) => {
                seenEntries = entries
                return Promise.resolve(true)
            },
        })

        expect(seenEntries).toEqual([
            ['resolved:@css/lazy-a', 3],
            ['resolved:@css/lazy-b', 1],
        ])
    })

    it.each([
        { loadResult: true, expectedErrorName: undefined },
        { loadResult: false, expectedErrorName: 'ChunkLoadError' },
    ])(
        'throws a ChunkLoadError only when the stylesheets fail to load (loadCss resolves $loadResult)',
        async ({ loadResult, expectedErrorName }) => {
            const { error } = await runPrelude(['lazy-a'], new Map([['lazy-a', 0]]), {
                loadCss: () => Promise.resolve(loadResult),
            })

            expect(error?.name).toBe(expectedErrorName)
        }
    )

    // A browser without import.meta.resolve cannot look up group URLs, so the prelude asks for the
    // full stylesheet instead of resolving anything.
    it('requests the full stylesheet instead when import.meta.resolve is unavailable', async () => {
        let seenEntries: unknown = 'not called'
        await runPrelude(['lazy-a'], new Map([['lazy-a', 0]]), {
            hasImportMetaResolve: false,
            loadCss: (entries) => {
                seenEntries = entries
                return Promise.resolve(true)
            },
        })

        expect(seenEntries).toBeNull()
    })
})
