import { planStableChunks } from './stableChunkNames.mjs'

// Two chunks: an entry that imports a shared chunk, the way esbuild writes them with publicPath /static.
const OUTPUTS = {
    'dist/Scene-AAAA1111.js': { entryPoint: 'src/scenes/Scene.tsx', inputs: { 'src/scenes/Scene.tsx': {} } },
    'dist/chunk-BBBB2222.js': { inputs: { 'src/lib/shared.ts': {}, 'src/lib/other.ts': {} } },
}

function plan(sources: Record<string, string>): Map<string, { stableFile: string; source: string }> {
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
        const { source } = plan(entry('export const a=1')).get('dist/Scene-AAAA1111.js')!

        expect(source).toMatch(/from"@c\/c[0-9A-F]{10}"/)
        expect(source).not.toContain('from"/static/chunk-BBBB2222.js"')
        expect(source).toContain('new URL("/static/chunk-BBBB2222.js")')
        expect(source).toContain('"/static/Inter-CCCC3333.woff2"')
    })
})
