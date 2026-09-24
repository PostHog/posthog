import { planStableChunks, stableFileName } from './stableChunkNames.mjs'

// Two chunks: an entry that imports a shared chunk, the way esbuild writes them with publicPath /static.
const OUTPUTS = {
    'dist/Scene-AAAA1111.js': { entryPoint: 'src/scenes/Scene.tsx', inputs: { 'src/scenes/Scene.tsx': {} } },
    'dist/chunk-BBBB2222.js': { inputs: { 'src/lib/shared.ts': {}, 'src/lib/other.ts': {} } },
}

function plan(sources: Record<string, string>): Map<string, { stableFile: string; source: string; mapValid: boolean }> {
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
    ])('%s', (_name, before, after, importerKeepsName) => {
        const [first, second] = [plan(before), plan(after)]
        expect(
            first.get('dist/Scene-AAAA1111.js')!.stableFile === second.get('dist/Scene-AAAA1111.js')!.stableFile
        ).toBe(importerKeepsName)
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

    // The copied source map is shifted down exactly one line, so the prelude must be a line of its own.
    it('puts a prelude on its own first line and names the chunk by it', () => {
        const sources = entry('export const a=1')
        const withPrelude = planStableChunks(
            OUTPUTS,
            (outputPath: string) => sources[outputPath],
            'dist/',
            new Map([['dist/Scene-AAAA1111.js', 'await window.ESBUILD_LOAD_CSS([]);']])
        ).plan.get('dist/Scene-AAAA1111.js')!

        expect(withPrelude.source.split('\n')[0]).toBe('await window.ESBUILD_LOAD_CSS([]);')
        expect(withPrelude.stableFile).not.toBe(plan(sources).get('dist/Scene-AAAA1111.js')!.stableFile)
    })
})
