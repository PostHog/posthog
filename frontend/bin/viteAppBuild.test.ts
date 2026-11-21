import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { finishViteAppBuild, planViteApp } from './viteAppBuild.mjs'

const FRONTEND = '/repo/frontend'
const URL_BASE = '/static/vite/'

interface Chunk {
    fileName: string
    name: string
    imports: string[]
    dynamicImports: string[]
    exports: string[]
    isEntry: boolean
    isDynamicEntry: boolean
    facadeModuleId: string | null
    css: string[]
}

function chunk(fileName: string, overrides: Partial<Chunk> = {}): Chunk {
    return {
        fileName,
        name: 'chunk',
        imports: [],
        dynamicImports: [],
        exports: [],
        isEntry: false,
        isDynamicEntry: false,
        facadeModuleId: null,
        css: [],
        ...overrides,
    }
}

const lazy = (fileName: string, module: string, overrides: Partial<Chunk> = {}): Chunk =>
    chunk(fileName, { isDynamicEntry: true, facadeModuleId: `${FRONTEND}/${module}`, ...overrides })

// The boot chain, one logged-out scene and one signed-in scene. Every scene imports `shared`.
const GRAPH: Chunk[] = [
    chunk('index-Vi-te001.js', {
        name: 'index',
        isEntry: true,
        facadeModuleId: `${FRONTEND}/src/index.tsx`,
        imports: ['chunk-shared.js'],
        dynamicImports: ['chunk-app.js', 'chunk-boot.js'],
        css: ['assets/index.css'],
    }),
    lazy('chunk-app.js', 'src/scenes/App.tsx', {
        imports: ['chunk-shared.js'],
        dynamicImports: ['chunk-shell.js', 'chunk-login.js', 'chunk-dashboards.js'],
        exports: ['App'],
        css: ['assets/app.css'],
    }),
    lazy('chunk-boot.js', 'src/scenes/bootApp.ts', { exports: ['bootApp'] }),
    lazy('chunk-shell.js', 'src/scenes/AuthenticatedShell.tsx', {
        exports: ['AuthenticatedShell'],
        css: ['assets/shell.css'],
    }),
    lazy('chunk-login.js', 'src/scenes/authentication/Login.tsx', {
        imports: ['chunk-shared.js', 'chunk-form.js'],
        exports: ['Login', 'scene'],
    }),
    lazy('chunk-dashboards.js', 'src/scenes/dashboard/Dashboards.tsx', {
        imports: ['chunk-shared.js', 'chunk-grid.js'],
        exports: ['Dashboards', 'scene'],
    }),
    chunk('chunk-shared.js'),
    chunk('chunk-form.js'),
    chunk('chunk-grid.js'),
]

const PLACEHOLDER: Record<string, string> = Object.fromEntries(
    GRAPH.filter((item) => !item.isEntry).map((item) => [
        item.fileName,
        item.fileName.replace('.js', '-placeholder.js'),
    ])
)

function plan(code: Record<string, string> = {}, sizes: Record<string, number> = {}): ReturnType<typeof planViteApp> {
    return planViteApp({
        graph: GRAPH,
        importMapUrls: Object.fromEntries(
            Object.entries(PLACEHOLDER).map(([fileName, placeholder]) => [URL_BASE + placeholder, URL_BASE + fileName])
        ),
        urlBase: URL_BASE,
        frontendDir: FRONTEND,
        signedInModules: new Set(['src/scenes/dashboard/Dashboards', 'src/scenes/AuthenticatedShell']),
        readCode: (fileName: string) => code[fileName] ?? `// ${fileName}`,
        fileSize: (fileName: string) => sizes[fileName] ?? 1,
    })
}

const placeholderUrl = (fileName: string): string => `static/vite/${PLACEHOLDER[fileName]}`

describe('planViteApp', () => {
    it('renames only the chunk whose bytes changed, and keeps every placeholder', () => {
        const before = plan()
        const after = plan({ 'chunk-grid.js': 'export const columns = 12' })

        const changed = [...after.finalNameOf].filter(([fileName, name]) => before.finalNameOf.get(fileName) !== name)
        expect(changed.map(([fileName]) => fileName)).toEqual(['chunk-grid.js'])
        // Vite's own hash can hold a dash, and it must not leak into the entry's name.
        expect(after.finalNameOf.get('index-Vi-te001.js')).toMatch(/^index-S[0-9A-F]{10}\.js$/)
        expect(Object.keys(after.manifest.imports)).toEqual(Object.keys(before.manifest.imports))
        expect(after.manifest.imports[placeholderUrl('chunk-grid.js')]).toEqual(
            `static/vite/${after.finalNameOf.get('chunk-grid.js')}`
        )
    })

    it('ignores the source map comment, which names the file', () => {
        const withComment = plan({
            'chunk-grid.js': 'export const columns = 12\n//# sourceMappingURL=chunk-grid.js.map\n',
        })
        const withoutComment = plan({ 'chunk-grid.js': 'export const columns = 12' })

        expect(withComment.finalNameOf.get('chunk-grid.js')).toEqual(withoutComment.finalNameOf.get('chunk-grid.js'))
    })

    it('refuses a chunk that names another chunk by its file, because the rename would break that reference', () => {
        expect(() => plan({ 'chunk-login.js': 'new Worker("/static/vite/chunk-form.js")' })).toThrow(
            'chunk-login.js names chunk-form.js directly'
        )
    })

    it('maps a lazy module to the chunks it needs beyond the boot chain, by its first named export', () => {
        const { chunkMap, finalNameOf } = plan()
        const scenes: Record<string, number[]> = chunkMap.scenes
        const filesOf = (key: string): string[] => scenes[key].map((index) => chunkMap.files[index]).sort()

        // `shared` is already loaded at boot, and `scene` is not a name the scene loader asks for.
        expect(filesOf('Dashboards')).toEqual(
            [finalNameOf.get('chunk-dashboards.js'), finalNameOf.get('chunk-grid.js')].sort()
        )
        expect(filesOf('Login')).toEqual([finalNameOf.get('chunk-login.js'), finalNameOf.get('chunk-form.js')].sort())
        expect(Object.keys(chunkMap.scenes).sort()).toEqual(['Dashboards', 'Login'])
    })

    it('leaves the chunks of signed-in scenes out of the logged-out import map', () => {
        const { manifest } = plan()

        expect([...manifest.loggedOutImports].sort()).toEqual(
            ['chunk-app.js', 'chunk-boot.js', 'chunk-form.js', 'chunk-login.js', 'chunk-shared.js']
                .map(placeholderUrl)
                .sort()
        )
    })

    it('links the stylesheets of the entry and only preloads those of the chunks it imports lazily', () => {
        const { manifest } = plan()

        expect(manifest.eagerCss).toEqual(['static/vite/assets/index.css'])
        expect(manifest.preload.css).toEqual(['static/vite/assets/app.css'])
        expect(manifest.preload.authenticatedCss).toEqual(['static/vite/assets/shell.css'])
    })

    it('preloads each root first, and a chunk under it only when it is large', () => {
        const url = (fileName: string, { finalNameOf }: ReturnType<typeof planViteApp>): string =>
            `static/vite/${finalNameOf.get(fileName) ?? fileName}`
        const roots = ['index-Vi-te001.js', 'chunk-app.js', 'chunk-boot.js']

        const small = plan({}, { 'chunk-shared.js': 10 })
        const large = plan({}, { 'chunk-shared.js': 200_000 })

        expect(small.manifest.preload.js).toEqual(roots.map((fileName) => url(fileName, small)))
        expect(large.manifest.preload.js).toEqual([...roots, 'chunk-shared.js'].map((fileName) => url(fileName, large)))
    })

    // A manifest that names a file the build did not write gives a page that fails to load. The page
    // then falls back to the esbuild build, so nobody sees an error.
    it('writes every file that its manifest names, and leaves no build metadata to serve', () => {
        const frontendDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vite-app-build-'))
        const outDir = path.join(frontendDir, 'dist', 'vite')
        fs.mkdirSync(path.join(outDir, 'assets'), { recursive: true })
        fs.mkdirSync(path.join(outDir, '.vite'))
        fs.mkdirSync(path.join(frontendDir, 'src', 'scenes'), { recursive: true })
        fs.writeFileSync(path.join(frontendDir, 'src', 'scenes', 'appScenes.ts'), '')
        fs.writeFileSync(path.join(frontendDir, 'src', 'productScenes.tsx'), '')
        // Vite deletes a chunk that held only CSS after the graph was recorded.
        const cssOnly = chunk('chunk-css-only.js')
        const graph = [...GRAPH, cssOnly].map((item) => ({
            ...item,
            facadeModuleId: item.facadeModuleId?.replace(FRONTEND, frontendDir) ?? null,
        }))
        for (const item of GRAPH) {
            fs.writeFileSync(
                path.join(outDir, item.fileName),
                `// ${item.fileName}\n//# sourceMappingURL=${item.fileName}.map\n`
            )
            fs.writeFileSync(path.join(outDir, `${item.fileName}.map`), '{}')
            item.css.forEach((file) => fs.writeFileSync(path.join(outDir, file), ''))
        }
        fs.writeFileSync(path.join(outDir, 'vite-app-graph.json'), JSON.stringify(graph))
        fs.writeFileSync(
            path.join(outDir, 'importmap.json'),
            JSON.stringify({
                imports: Object.fromEntries(
                    [...Object.entries(PLACEHOLDER), [cssOnly.fileName, 'chunk-css-only-placeholder.js']].map(
                        ([fileName, placeholder]) => [URL_BASE + placeholder, URL_BASE + fileName]
                    )
                ),
            })
        )
        jest.spyOn(console, 'info').mockImplementation(() => {})

        finishViteAppBuild(frontendDir)

        const manifest = JSON.parse(fs.readFileSync(path.join(outDir, 'vite-app-manifest.json'), 'utf8'))
        const named: string[] = [
            manifest.entry,
            manifest.chunkMap,
            ...Object.values<string>(manifest.imports),
            ...manifest.eagerCss,
            ...Object.values<string[]>(manifest.preload).flat(),
        ]
        const onDisk = (url: string): string => path.join(outDir, url.replace(manifest.assetPrefix, ''))
        expect(named.filter((url) => !fs.existsSync(onDisk(url)))).toEqual([])
        expect(Object.keys(manifest.imports)).not.toContain('static/vite/chunk-css-only-placeholder.js')

        const entry = onDisk(manifest.entry)
        expect(fs.readFileSync(entry, 'utf8')).toMatch(new RegExp(`sourceMappingURL=${path.basename(entry)}\\.map\\n$`))
        expect(fs.existsSync(`${entry}.map`)).toBe(true)

        expect(
            fs
                .readdirSync(outDir)
                .filter((file) => /^(\.vite|importmap\.json|vite-app-graph\.json|index-Vi-te001\.js.*)$/.test(file))
        ).toEqual([])
        fs.rmSync(frontendDir, { recursive: true, force: true })
    })
})
