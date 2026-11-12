import { describe, expect, test } from 'bun:test'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { CATALOG_SCHEMA, CATALOG_TOOLS_JSON, compiledFiles, findCatalogGaps, type GapResult } from './catalog-gap'

const GENERATED = 'services/mcp/src/tools/generated/actions.ts'

function generated(...tools: string[]): string {
    return `import x from 'y'\n\nexport const GENERATED_TOOLS = {\n${tools.map((tool) => `    '${tool}': factory,`).join('\n')}\n}\n`
}

const CATALOG = JSON.stringify({ 'action-get': {}, 'action-create': {} })

function gaps(changed: string[], head: Record<string, string>, base: Record<string, string> = {}): GapResult {
    return findCatalogGaps({
        changed,
        compiled: new Set([
            'hog/src/cli.ts',
            GENERATED,
            'services/mcp/src/tools/generated/hooks.ts',
            'services/mcp/src/tools/featureFlags/conditionIdHooks.ts',
            'services/mcp/schema/tool-definitions.json',
            CATALOG_SCHEMA,
        ]),
        readBase: (path) => base[path],
        readHead: (path) => ({ [CATALOG_TOOLS_JSON]: CATALOG, ...head })[path],
    })
}

describe('catalog gaps', () => {
    test.each([
        ['a hog source file', ['hog/src/cli.ts'], {}],
        ['the hook registry', ['services/mcp/src/tools/generated/hooks.ts'], {}],
        ['a hand-written hook', ['services/mcp/src/tools/featureFlags/conditionIdHooks.ts'], {}],
        [
            'a generated tool the catalog leaves out',
            [GENERATED],
            { [GENERATED]: generated('action-get', 'action-delete') },
        ],
        [
            'the definition of a tool the catalog leaves out',
            ['services/mcp/schema/tool-definitions.json'],
            { 'services/mcp/schema/tool-definitions.json': JSON.stringify({ 'exec-tool': { summary: 'new' } }) },
        ],
    ])('needs a patch release for %s', (_name, changed, head) => {
        const result = gaps(changed, head)

        expect(result).toMatchObject({ needsRelease: true, bump: 'patch' })
        expect(result.reasons.map((reason) => reason.file)).toEqual(changed)
    })

    test.each([
        ['generated tools the catalog carries', [GENERATED], { [GENERATED]: generated('action-get', 'action-create') }],
        [
            'definitions of tools the catalog carries',
            ['services/mcp/schema/tool-definitions.json'],
            { 'services/mcp/schema/tool-definitions.json': JSON.stringify({ 'action-get': { summary: 'new' } }) },
        ],
        ['the catalog data itself', [CATALOG_TOOLS_JSON], {}],
        ['files hog does not compile', ['hog/src/cli.test.ts', 'services/mcp/src/hono/app.ts'], {}],
    ])('needs no release for %s', (_name, changed, head) => {
        expect(gaps(changed, head)).toEqual({ needsRelease: false, bump: 'patch', reasons: [] })
    })

    test('counts a tool removed from a generated file, which the catalog no longer carries', () => {
        const result = gaps(
            [GENERATED],
            { [GENERATED]: generated('action-get') },
            { [GENERATED]: generated('action-get', 'action-delete') }
        )

        expect(result.needsRelease).toBe(true)
        expect(result.reasons[0]?.why).toContain('action-delete')
    })

    test('needs a minor release when the catalog format version changes', () => {
        const schema = (version: number): string => `export const CATALOG_SCHEMA_VERSION = ${version}\n`

        const result = gaps([CATALOG_SCHEMA], { [CATALOG_SCHEMA]: schema(2) }, { [CATALOG_SCHEMA]: schema(1) })

        expect(result).toMatchObject({ needsRelease: true, bump: 'minor' })
    })
})

test('reads compiled files from metafiles relative to the folder each build ran in', async () => {
    const folder = await mkdtemp(join(tmpdir(), 'hog-metafile-'))
    const metafile = join(folder, 'meta.json')
    await writeFile(
        metafile,
        JSON.stringify({
            inputs: {
                'src/cli/library.ts': {},
                '../../node_modules/.pnpm/zod/index.js': {},
                'dist/cli-library.mjs': {},
                '../../hog/src/version.ts': {},
            },
        })
    )

    const files = compiledFiles([{ path: metafile, root: '/repo/services/mcp' }], '/repo')

    expect([...files].sort()).toEqual(['hog/src/version.ts', 'services/mcp/src/cli/library.ts'])
})
