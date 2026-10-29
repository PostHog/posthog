import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { loggedOutSpecifiers, planStableChunks, shiftMappingsForPrelude, stableFileName } from './stableChunkNames.mjs'

// Two chunks: an entry that imports a shared chunk, the way esbuild writes them with publicPath /static.
const OUTPUTS = {
    'dist/Scene-AAAA1111.js': { entryPoint: 'src/scenes/Scene.tsx', inputs: { 'src/scenes/Scene.tsx': {} } },
    'dist/chunk-BBBB2222.js': { inputs: { 'src/lib/shared.ts': {}, 'src/lib/other.ts': {} } },
}

function plan(sources: Record<string, string>): Map<string, { source: string; mapValid: boolean }> {
    return planStableChunks(OUTPUTS, (outputPath: string) => sources[outputPath]).plan
}

describe('planStableChunks', () => {
    const entry = (shared: string, own = 'render()'): Record<string, string> => ({
        'dist/Scene-AAAA1111.js': `import{a}from"/static/chunk-BBBB2222.js";${own};new URL("/static/Inter-CCCC3333.woff2");new Worker(new URL("/static/chunk-BBBB2222.js"))`,
        'dist/chunk-BBBB2222.js': shared,
    })

    // The point of the step: a changed chunk must not rename the chunks that import it, or returning
    // users download those again after every deploy.
    it.each([
        [
            'keeps the importer when only the imported chunk changes',
            entry('export const a=1'),
            entry('export const a=2'),
            true,
        ],
        [
            'renames the importer when its own code changes',
            entry('export const a=1'),
            entry('export const a=1', 'renderAgain()'),
            false,
        ],
    ])('%s', (_name, before, after, importerKeepsSource) => {
        const [first, second] = [plan(before), plan(after)]
        expect(first.get('dist/Scene-AAAA1111.js')!.source === second.get('dist/Scene-AAAA1111.js')!.source).toBe(
            importerKeepsSource
        )
    })

    it('rewrites chunk imports to identity specifiers and leaves URLs alone', () => {
        const before = entry('export const a=1')
        const { source } = plan(before).get('dist/Scene-AAAA1111.js')!

        expect(source).toMatch(/from"@c\/c[0-9A-F]{10}"/)
        expect(source).not.toContain('from"/static/chunk-BBBB2222.js"')
        expect(source).toContain('new URL("/static/chunk-BBBB2222.js")')
        expect(source).toContain('"/static/Inter-CCCC3333.woff2"')
    })

    it('pads a shorter specifier so the rewritten source keeps its original length', () => {
        const before = entry('export const a=1')
        const { source, mapValid } = plan(before).get('dist/Scene-AAAA1111.js')!

        expect(source.length).toBe(before['dist/Scene-AAAA1111.js'].length)
        expect(source).toMatch(/from"@c\/c[0-9A-F]{10}" +;/)
        expect(mapValid).toBe(true)
    })

    describe('identity collisions', () => {
        afterEach(() => jest.restoreAllMocks())

        it('warns and falls back to a unique name when two chunks share an identity', () => {
            // Two chunks with no inputs hash to the same identity (see the comment in the source).
            const outputs = {
                'dist/chunk-EEEE0000.js': {},
                'dist/chunk-FFFF0000.js': {},
            }
            const warn = jest.spyOn(console, 'warn').mockImplementation(() => {})

            const { plan: collisionPlan } = planStableChunks(outputs, () => '')

            expect(warn).toHaveBeenCalledWith(expect.stringContaining('identity collision for dist/chunk-'))
            expect(collisionPlan.get('dist/chunk-EEEE0000.js')!.identity).not.toBe(
                collisionPlan.get('dist/chunk-FFFF0000.js')!.identity
            )
        })

        it('marks the map invalid when a collision fallback identity outgrows a short chunk name', () => {
            // Both empty-input chunks hash to the same identity; the second falls back to a longer
            // one (its own identity plus a hash of its output path), which can outgrow a short
            // original file name and make the replacement longer than the specifier it replaces.
            const outputs = {
                'dist/c-a.js': {},
                'dist/c-b.js': {},
                'dist/e-x.js': { entryPoint: 'src/x.tsx', inputs: { 'src/x.tsx': {} } },
            }
            const sources: Record<string, string> = {
                'dist/c-a.js': '',
                'dist/c-b.js': '',
                'dist/e-x.js': 'from"/static/c-b.js";render()',
            }
            jest.spyOn(console, 'warn').mockImplementation(() => {})

            const { plan: collisionPlan } = planStableChunks(outputs, (outputPath: string) => sources[outputPath])

            expect(collisionPlan.get('dist/e-x.js')!.mapValid).toBe(false)
        })
    })

    describe('stableFileName', () => {
        it('throws when the esbuild output name has no -<hash> suffix to replace', () => {
            expect(() => stableFileName('index.js', 'source')).toThrow(/does not end in the expected/)
        })
    })

    // Pins the one-line shift so a regression here doesn't only show up as misattributed stack traces.
    describe('shiftMappingsForPrelude', () => {
        it('adds one leading empty generated line to the mappings', () => {
            expect(shiftMappingsForPrelude('AAAA')).toBe(';AAAA')
        })
    })

    // The copied source map is shifted down exactly one line, so the prelude must be a line of its own.
    it('puts a prelude on its own first line, keyed by the chunk specifier', () => {
        const sources = entry('export const a=1')
        const withPrelude = planStableChunks(
            OUTPUTS,
            (outputPath: string) => sources[outputPath],
            'dist/',
            new Map([['dist/Scene-AAAA1111.js', (specifier: string) => `register(${JSON.stringify(specifier)});`]])
        ).plan.get('dist/Scene-AAAA1111.js')!

        expect(withPrelude.source.split('\n')[0]).toMatch(/^register\("@c\/e[0-9A-F]{10}"\);$/)
    })

    it('imports a chunk with a prelude dynamically through the stylesheet-aware loader, and statically as is', () => {
        const outputs = {
            ...OUTPUTS,
            'dist/Lazy-DDDD4444.js': { entryPoint: 'src/scenes/Lazy.tsx', inputs: { 'src/scenes/Lazy.tsx': {} } },
        }
        const importer =
            'import("/static/Lazy-DDDD4444.js");import("/static/chunk-BBBB2222.js");import"/static/Lazy-DDDD4444.js"'
        const { plan: lazyPlan } = planStableChunks(
            outputs,
            (outputPath: string) => (outputPath === 'dist/Scene-AAAA1111.js' ? importer : ''),
            'dist/',
            new Map([['dist/Lazy-DDDD4444.js', () => 'register();']])
        )
        const { source, mapValid } = lazyPlan.get('dist/Scene-AAAA1111.js')!

        expect(source).toMatch(
            /^ESBUILD_IMPORT\("@c\/e[0-9A-F]{10}" *\);import\("@c\/c[0-9A-F]{10}" *\);import"@c\/e[0-9A-F]{10}" *$/
        )
        expect(mapValid).toBe(true)
    })

    describe('writeStableChunks', () => {
        interface Written {
            files: Record<string, string>
            stableFileOf: (outputPath: string) => string
        }

        // esbuild refuses to load under jsdom, so the writer runs in a node process of its own.
        function runWriter(
            absWorkingDir: string,
            outputs: Record<string, object>,
            preludes: Record<string, string>
        ): any {
            const script = `
                const { writeStableChunks } = await import(${JSON.stringify(path.join(__dirname, 'stableChunkNames.mjs'))})
                const [absWorkingDir, outputs, preludes] = JSON.parse(process.argv[1])
                const { manifest } = await writeStableChunks({
                    absWorkingDir,
                    outputs,
                    chunks: {},
                    entrypoints: [],
                    preloadManifest: undefined,
                    preludes: new Map(Object.entries(preludes).map(([file, prelude]) => [file, () => prelude])),
                    target: 'es2020',
                })
                process.stdout.write(JSON.stringify(manifest))
            `
            const result = spawnSync(
                'node',
                ['--input-type=module', '-e', script, JSON.stringify([absWorkingDir, outputs, preludes])],
                { encoding: 'utf8' }
            )
            if (result.status !== 0) {
                throw new Error(result.stderr)
            }
            return JSON.parse(result.stdout)
        }

        function write(
            outputs: Record<string, object>,
            sources: Record<string, string>,
            preludes: Record<string, string> = {}
        ): Written {
            const absWorkingDir = mkdtempSync(path.join(tmpdir(), 'stable-chunks-'))
            try {
                const distDir = path.join(absWorkingDir, 'dist')
                mkdirSync(distDir, { recursive: true })
                for (const [outputPath, source] of Object.entries(sources)) {
                    writeFileSync(path.join(absWorkingDir, outputPath), source)
                }

                const manifest = runWriter(absWorkingDir, outputs, preludes)

                const files = Object.fromEntries(
                    readdirSync(distDir).map((file) => [file, readFileSync(path.join(distDir, file), 'utf8')])
                )
                const { plan: written } = planStableChunks(outputs, (outputPath: string) => sources[outputPath])
                const stableFileOf = (outputPath: string): string =>
                    manifest.imports[`@c/${written.get(outputPath)!.identity}`].replace(/^static\//, '')
                return { files, stableFileOf }
            } finally {
                rmSync(absWorkingDir, { recursive: true, force: true })
            }
        }

        // Minified while bundling, an unchanged library chunk got new bytes, and a new name, on most deploys.
        it('keeps a chunk stable name when only a chunk it imports changes', () => {
            const library = 'const someLongLibraryName=function(){return 1};export{someLongLibraryName as a};'
            const sources = (render: string): Record<string, string> => ({
                'dist/Scene-AAAA1111.js': `import{a as libraryValue}from"/static/chunk-BBBB2222.js";${render}`,
                'dist/chunk-BBBB2222.js': library,
            })

            const before = write(OUTPUTS, sources('console.log(libraryValue())'))
            const after = write(OUTPUTS, sources('console.log(libraryValue(),2)'))

            const libraryFile = before.stableFileOf('dist/chunk-BBBB2222.js')
            expect(after.stableFileOf('dist/chunk-BBBB2222.js')).toBe(libraryFile)
            expect(after.stableFileOf('dist/Scene-AAAA1111.js')).not.toBe(before.stableFileOf('dist/Scene-AAAA1111.js'))
            expect(before.files[libraryFile]).not.toContain('someLongLibraryName')
        })

        // The prelude becomes part of the bytes a chunk's stable name hashes, so adding one must
        // give the chunk a new name, the same as any other change to its own code.
        it('gives a chunk a new stable name when a prelude is added', () => {
            const outputs = {
                'dist/Lazy-DDDD4444.js': { entryPoint: 'src/scenes/Lazy.tsx', inputs: { 'src/scenes/Lazy.tsx': {} } },
            }
            const sources = { 'dist/Lazy-DDDD4444.js': 'console.log(1)' }

            const noPrelude = write(outputs, sources)
            const withPrelude = write(outputs, sources, { 'dist/Lazy-DDDD4444.js': 'register();' })

            expect(withPrelude.stableFileOf('dist/Lazy-DDDD4444.js')).not.toBe(
                noPrelude.stableFileOf('dist/Lazy-DDDD4444.js')
            )
        })

        // A wrong map only shows up later, as stack traces that point at the wrong code.
        it.each([
            ['a prelude chunk', { 'dist/entry-AAAA1111.js': 'register();' }],
            ['a chunk with no prelude', {}],
        ])('points the source map of %s back at the original source', (_name, preludes) => {
            const outputs = {
                'dist/entry-AAAA1111.js': { entryPoint: 'src/entry.tsx', inputs: { 'src/entry.tsx': {} } },
            }
            const { files, stableFileOf } = write(
                outputs,
                {
                    'dist/entry-AAAA1111.js': 'console.log(1)\n//# sourceMappingURL=entry-AAAA1111.js.map\n',
                    'dist/entry-AAAA1111.js.map': JSON.stringify({
                        version: 3,
                        sources: ['../src/entry.tsx'],
                        sourcesContent: ['console.log(1)'],
                        names: [],
                        mappings: 'AAAA',
                    }),
                },
                preludes
            )

            const stableFile = stableFileOf('dist/entry-AAAA1111.js')
            expect(files[stableFile]).toContain(`//# sourceMappingURL=${stableFile}.map`)
            const map = JSON.parse(files[`${stableFile}.map`])
            expect(map.sources).toEqual(['../src/entry.tsx'])
            expect(map.sourcesContent).toEqual(['console.log(1)'])
        })
    })

    describe('loggedOutSpecifiers', () => {
        // The entry imports App, which lazy-loads a logged-out scene, a signed-in scene and a helper.
        const WALK_OUTPUTS = {
            'dist/index-AAAA1111.js': {
                entryPoint: 'src/index.tsx',
                imports: [{ path: 'dist/App-BBBB2222.js', kind: 'dynamic-import' }],
            },
            'dist/App-BBBB2222.js': {
                entryPoint: 'src/scenes/App.tsx',
                imports: [
                    { path: 'dist/Login-CCCC3333.js', kind: 'dynamic-import' },
                    { path: 'dist/Insight-DDDD4444.js', kind: 'dynamic-import' },
                    { path: 'dist/helper-EEEE5555.js', kind: 'dynamic-import' },
                ],
            },
            'dist/Login-CCCC3333.js': {
                entryPoint: 'src/scenes/Login.tsx',
                imports: [{ path: 'dist/chunk-FFFF6666.js', kind: 'import-statement' }],
            },
            'dist/Insight-DDDD4444.js': {
                entryPoint: '../products/insights/Insight.tsx',
                imports: [{ path: 'dist/chunk-GGGG7777.js', kind: 'import-statement' }],
            },
            'dist/helper-EEEE5555.js': { entryPoint: 'src/lib/helper.ts', imports: [] },
            'dist/chunk-FFFF6666.js': { inputs: { 'src/lib/form.ts': {} }, imports: [] },
            'dist/chunk-GGGG7777.js': { inputs: { 'src/lib/chart.ts': {} }, imports: [] },
        }
        const walkPlan = planStableChunks(WALK_OUTPUTS, () => 'export {}', 'dist/').plan
        const specifierOf = (outputPath: string): string => `@c/${walkPlan.get(outputPath)!.identity}`
        const walk = (loggedOutModules: string[]): string[] =>
            loggedOutSpecifiers(WALK_OUTPUTS, walkPlan, {
                entry: 'src/index.tsx',
                loggedOutModules: new Set(loggedOutModules),
                signedInModules: new Set(['../products/insights/Insight']),
                cssSpecifiersByOutput: new Map([
                    ['dist/Login-CCCC3333.js', ['@css/login']],
                    ['dist/Insight-DDDD4444.js', ['@css/insight']],
                ]),
            })

        it('keeps what a logged-out page can load and drops the chunks of signed-in scenes', () => {
            expect(walk(['src/scenes/Login'])).toEqual(
                [
                    ...[
                        'dist/index-AAAA1111.js',
                        'dist/App-BBBB2222.js',
                        'dist/Login-CCCC3333.js',
                        'dist/helper-EEEE5555.js',
                        'dist/chunk-FFFF6666.js',
                    ].map(specifierOf),
                    '@css/login',
                ].sort()
            )
        })

        it('fails when a logged-out scene is not reachable from the entry', () => {
            expect(() => walk(['src/scenes/Login', 'src/scenes/Renamed'])).toThrow('src/scenes/Renamed')
        })
    })
})
