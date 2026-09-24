import { planCssGroups } from './stableCssPlan.mjs'

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

    // Interleaving two same-owner stylesheets with a different group's file would merge them out of order.
    it('fails rather than reorder rules when a lazy group is not contiguous', () => {
        const nonContiguous = {
            inputs: {
                'src/index.tsx': imports(),
                'src/scenes/App.tsx': imports(),
                'src/scenes/Scene.tsx': imports('src/lib/Shared.tsx'),
                'src/lib/Shared.tsx': imports('src/lib/Shared1.scss', 'src/lib/Shared2.scss'),
                'src/scenes/Other.tsx': imports('src/scenes/Other.scss'),
                'src/lib/Shared1.scss': imports(),
                'src/scenes/Other.scss': imports(),
                'src/lib/Shared2.scss': imports(),
            },
            outputs: {
                'dist/index-A.js': {
                    entryPoint: 'src/index.tsx',
                    cssBundle: 'dist/index-A.css',
                    inputs: { 'src/index.tsx': {} },
                },
                'dist/index-A.css': {
                    inputs: {
                        'src/lib/Shared1.scss': {},
                        'src/scenes/Other.scss': {},
                        'src/lib/Shared2.scss': {},
                    },
                },
                'dist/App-B.js': { entryPoint: 'src/scenes/App.tsx', inputs: { 'src/scenes/App.tsx': {} } },
                'dist/Scene-C.js': {
                    entryPoint: 'src/scenes/Scene.tsx',
                    inputs: { 'src/scenes/Scene.tsx': {} },
                    imports: [{ path: 'dist/chunk-D.js', kind: 'import-statement' }],
                },
                'dist/chunk-D.js': { inputs: { 'src/lib/Shared.tsx': {} } },
                'dist/Other-E.js': { entryPoint: 'src/scenes/Other.tsx', inputs: { 'src/scenes/Other.tsx': {} } },
            },
        }

        expect(() => planCssGroups(nonContiguous)).toThrow('is not contiguous')
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
})
