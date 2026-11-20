import { describe, expect, test } from 'bun:test'
import { execFileSync } from 'node:child_process'
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
    CATALOG_SCHEMA,
    CATALOG_TOOLS_JSON,
    compiledFiles,
    findCatalogGaps,
    type GapResult,
    outsideCheckout,
    outsideReleasePaths,
    readAt,
    releaseBuildInputs,
    releaseCheckoutPatterns,
    untriggeredFiles,
} from './catalog-gap'

const GENERATED = 'services/mcp/src/tools/generated/actions.ts'
const UNCARRIED_MODULE = 'services/mcp/src/tools/generated/workflows.ts'
const SCHEMAS = 'services/mcp/src/generated/actions/api.ts'
const SHARED_SCHEMAS = 'services/mcp/src/generated/workflows/api.ts'
const HAND_WRITTEN_TOOL = 'services/mcp/src/tools/workflows/lifecycle.ts'
const REGISTRY = 'services/mcp/src/tools/generated/index.ts'
const ALIASES = 'services/mcp/src/tools/actions/deprecatedAliases.ts'

const pascal = (tool: string): string =>
    tool.replace(/(^|-)([a-z0-9])/g, (_, __, letter: string) => letter.toUpperCase())
const camel = (tool: string): string => pascal(tool).replace(/^./, (letter) => letter.toLowerCase())

function generated(...tools: string[]): string {
    const blocks = tools.map(
        (tool) =>
            `const ${pascal(tool)}Schema = () => orvalSchemas.${pascal(tool)}()\n\n` +
            `const ${camel(tool)} = (): ToolBase => ({\n    name: '${tool}',\n    schema: ${pascal(tool)}Schema(),\n})\n`
    )
    const map = tools.map((tool) => `    '${tool}': ${camel(tool)},`).join('\n')
    return `import * as orvalSchemas from '@/generated/api'\n\n${blocks.join('\n')}\nexport const GENERATED_TOOLS = {\n${map}\n}\n`
}

function schemas(descriptions: Record<string, string>, prelude = "import * as zod from 'zod'"): string {
    const blocks = Object.entries(descriptions).map(
        ([name, description]) =>
            `/**\n * @summary ${name}\n */\nexport const ${name} = () => zod.object({\n    id: zod.string().describe('${description}'),\n})\n`
    )
    return `${prelude}\n\n${blocks.join('\n')}`
}

function lifecycleTool(...names: string[]): string {
    return `import { ${names.join(', ')} } from '@/generated/workflows/api'\n\nexport const tool = () => null\n`
}

const FETCH = "void fetch('https://example.com/collect')"

const CATALOG = JSON.stringify({ 'action-get': {}, 'action-create': {}, 'workflows-get': {} })
const WORKFLOW_SCHEMAS = {
    WorkflowsGet: 'a workflow',
    WorkflowsPatchGraph: 'a graph',
    HogFlowsPartialUpdateParams: 'a flow',
}

function registry(...modules: string[]): string {
    return [
        "import type { ToolBase, ZodObjectAny } from '@/tools/types'",
        ...modules.map((module) => `import { GENERATED_TOOLS as ${module} } from './${module}'`),
        'export const GENERATED_TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {',
        ...modules.map((module) => `    ...${module},`),
        '}',
    ].join('\n')
}

const MODULES = {
    [GENERATED]: generated('action-get', 'action-create'),
    [UNCARRIED_MODULE]: generated('workflows-get', 'workflows-patch-graph'),
    [HAND_WRITTEN_TOOL]: lifecycleTool('HogFlowsPartialUpdateParams'),
    [SCHEMAS]: schemas({ ActionGet: 'an action', ActionCreate: 'a new action' }),
    [SHARED_SCHEMAS]: schemas(WORKFLOW_SCHEMAS),
}

function gaps(
    changed: string[],
    head: Record<string, string>,
    base: Record<string, string> = {},
    importers: [string, string[]][] = []
): GapResult {
    return findCatalogGaps({
        changed,
        compiled: {
            files: new Set([
                'hog/src/cli.ts',
                GENERATED,
                UNCARRIED_MODULE,
                SCHEMAS,
                SHARED_SCHEMAS,
                HAND_WRITTEN_TOOL,
                REGISTRY,
                ALIASES,
                'services/mcp/src/tools/generated/hooks.ts',
                'services/mcp/src/tools/featureFlags/conditionIdHooks.ts',
                'services/mcp/schema/tool-definitions.json',
                CATALOG_SCHEMA,
            ]),
            importers: new Map([
                [SCHEMAS, new Set([GENERATED])],
                [SHARED_SCHEMAS, new Set([UNCARRIED_MODULE, HAND_WRITTEN_TOOL])],
                ...importers.map(([file, from]): [string, Set<string>] => [file, new Set(from)]),
            ]),
            specifiers: new Map([[SHARED_SCHEMAS, new Map([[HAND_WRITTEN_TOOL, ['@/generated/workflows/api']]])]]),
        },
        readBase: (path) => ({ ...MODULES, ...base })[path],
        readHead: (path) => ({ [CATALOG_TOOLS_JSON]: CATALOG, ...MODULES, ...head })[path],
    })
}

describe('catalog gaps', () => {
    test.each([
        ['a hog source file', ['hog/src/cli.ts'], {}, {}],
        ['the hook registry', ['services/mcp/src/tools/generated/hooks.ts'], {}, {}],
        ['a hand-written hook', ['services/mcp/src/tools/featureFlags/conditionIdHooks.ts'], {}, {}],
        [
            'a generated tool the catalog leaves out',
            [GENERATED],
            { [GENERATED]: generated('action-get', 'action-delete') },
            {},
        ],
        [
            'the definition of a tool the catalog leaves out',
            ['services/mcp/schema/tool-definitions.json'],
            { 'services/mcp/schema/tool-definitions.json': JSON.stringify({ 'exec-tool': { summary: 'new' } }) },
            {},
        ],
        [
            'a generated schema a tool the catalog leaves out reads',
            [SHARED_SCHEMAS],
            { [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, WorkflowsPatchGraph: 'a new graph' }) },
            {},
        ],
        [
            'a generated schema a hand-written tool imports',
            [SHARED_SCHEMAS],
            { [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, HogFlowsPartialUpdateParams: 'a new flow' }) },
            {},
        ],
        [
            'a generated schema file a hand-written tool also loads with import()',
            [SHARED_SCHEMAS],
            {
                [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, WorkflowsGet: 'a newer workflow' }),
                [HAND_WRITTEN_TOOL]: `${lifecycleTool('HogFlowsPartialUpdateParams')}export const later = () => import("@/generated/workflows/api")\n`,
            },
            {},
        ],
        [
            'a generated schema a hand-written tool imports with a comment between the braces',
            [SHARED_SCHEMAS],
            {
                [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, HogFlowsPartialUpdateParams: 'a new flow' }),
                [HAND_WRITTEN_TOOL]: lifecycleTool('HogFlowsPartialUpdateParams /* the flow to update */'),
            },
            {},
        ],
        [
            'a generated schema a hand-written tool imports through an escaped specifier, below a commented-out import',
            [SHARED_SCHEMAS],
            {
                [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, HogFlowsPartialUpdateParams: 'a new flow' }),
                [HAND_WRITTEN_TOOL]: `// import { WorkflowsGet } from '@/generated/workflows/api'\nimport { HogFlowsPartialUpdateParams } from '@\\u002fgenerated/workflows/api'\n`,
            },
            {},
        ],
        [
            'a module dropped from the registry spread while its import stays',
            [REGISTRY],
            { [REGISTRY]: registry('actions', 'workflows').replace('\n    ...workflows,', '') },
            { [REGISTRY]: registry('actions', 'workflows') },
        ],
        [
            'a generated schema file change outside its schemas',
            [SHARED_SCHEMAS],
            { [SHARED_SCHEMAS]: schemas(WORKFLOW_SCHEMAS, "import * as zod from 'zod/v4'") },
            {},
        ],
        [
            'a generated schema file line that runs code after a comment',
            [SCHEMAS],
            { [SCHEMAS]: `${MODULES[SCHEMAS]}/** @license MIT */ ${FETCH}\n` },
            {},
        ],
        [
            'a generated schema file line that continues an expression with a call',
            [SCHEMAS],
            { [SCHEMAS]: `${MODULES[SCHEMAS]}export const limit = 2\n    * ${FETCH.replace('void ', '')}\n` },
            {},
        ],
        [
            'a call added to a generated schema file only carried tools read',
            [SCHEMAS],
            { [SCHEMAS]: `${MODULES[SCHEMAS]}const telemetry = (() => { ${FETCH} })()\n` },
            {},
        ],
        [
            'a schema only carried tools read, in a generated schema file with top-level code',
            [SCHEMAS],
            { [SCHEMAS]: `${schemas({ ActionGet: 'an action', ActionCreate: 'a newer action' })}${FETCH}\n` },
            { [SCHEMAS]: `${MODULES[SCHEMAS]}${FETCH}\n` },
        ],
        [
            'a generated schema that reaches the Function constructor through zod',
            [SCHEMAS],
            { [SCHEMAS]: `${MODULES[SCHEMAS]}export const Built = zod.constructor.constructor("${FETCH}")()\n` },
            {},
        ],
        [
            'top-level code added to a generated module whose tools the catalog carries',
            [GENERATED],
            { [GENERATED]: `${MODULES[GENERATED]}${FETCH}\n` },
            {},
        ],
        [
            'a function the prelude of a carried generated module calls',
            [GENERATED],
            { [GENERATED]: `${MODULES[GENERATED]}function setup() { ${FETCH} }\nsetup()\n` },
            { [GENERATED]: `${MODULES[GENERATED]}function setup() {}\nsetup()\n` },
        ],
        [
            'a function a carried generated module calls through a computed global',
            [GENERATED],
            { [GENERATED]: `${MODULES[GENERATED]}function setup() { ${FETCH} }\nglobalThis['set' + 'up']()\n` },
            { [GENERATED]: `${MODULES[GENERATED]}function setup() {}\nglobalThis['set' + 'up']()\n` },
        ],
        [
            'a const that a function the prelude of a schema file calls reads',
            [SCHEMAS],
            {
                [SCHEMAS]: `${MODULES[SCHEMAS]}const host = 'b.example.com'\nfunction setup() { void fetch(host) }\nsetup()\n`,
            },
            {
                [SCHEMAS]: `${MODULES[SCHEMAS]}const host = 'a.example.com'\nfunction setup() { void fetch(host) }\nsetup()\n`,
            },
        ],
        [
            'a registered module whose tools the catalog carries, with top-level code',
            [REGISTRY],
            { [REGISTRY]: registry('actions'), [GENERATED]: `${MODULES[GENERATED]}${FETCH}\n` },
            { [REGISTRY]: registry() },
        ],
        [
            'a registered module whose tools the catalog leaves out',
            [REGISTRY],
            { [REGISTRY]: registry('actions', 'workflows') },
            { [REGISTRY]: registry('actions') },
        ],
        [
            'a registry change beyond its module list',
            [REGISTRY],
            { [REGISTRY]: `${registry('actions')}\nexport const COUNT = 1` },
            { [REGISTRY]: registry('actions') },
        ],
    ])('needs a patch release for %s', (_name, changed, head: Record<string, string>, base: Record<string, string>) => {
        const result = gaps(changed, head, base)

        expect(result).toMatchObject({ needsRelease: true, bump: 'patch' })
        expect(result.reasons.map((reason) => reason.file)).toEqual(changed)
    })

    test.each([
        [
            'generated tools the catalog carries',
            [GENERATED],
            { [GENERATED]: generated('action-get', 'action-create') },
            {},
        ],
        [
            'definitions of tools the catalog carries',
            ['services/mcp/schema/tool-definitions.json'],
            { 'services/mcp/schema/tool-definitions.json': JSON.stringify({ 'action-get': { summary: 'new' } }) },
            {},
        ],
        ['the catalog data itself', [CATALOG_TOOLS_JSON], {}, {}],
        ['files hog does not compile', ['hog/src/cli.test.ts', 'services/mcp/src/hono/app.ts'], {}, {}],
        [
            'generated schemas only a module the catalog carries reads',
            [SCHEMAS],
            { [SCHEMAS]: schemas({ ActionGet: 'an action', ActionCreate: 'a newer action' }) },
            {},
        ],
        [
            'a generated schema only tools the catalog carries read',
            [SHARED_SCHEMAS],
            { [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, WorkflowsGet: 'a newer workflow' }) },
            {},
        ],
        [
            'a generated schema a hand-written tool imports with import type',
            [SHARED_SCHEMAS],
            {
                [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, HogFlowsPartialUpdateParams: 'a new flow' }),
                [HAND_WRITTEN_TOOL]: lifecycleTool('HogFlowsPartialUpdateParams').replace('import {', 'import type {'),
            },
            {},
        ],
        [
            'a generated schema a hand-written tool imports only as a type binding',
            [SHARED_SCHEMAS],
            {
                [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, HogFlowsPartialUpdateParams: 'a new flow' }),
                [HAND_WRITTEN_TOOL]: lifecycleTool('type HogFlowsPartialUpdateParams'),
            },
            {},
        ],
        [
            'a registered module whose tools the catalog carries',
            [REGISTRY],
            { [REGISTRY]: registry('actions') },
            { [REGISTRY]: registry() },
        ],
    ])('needs no release for %s', (_name, changed, head: Record<string, string>, base: Record<string, string>) => {
        expect(gaps(changed, head, base)).toEqual({ needsRelease: false, bump: 'patch', reasons: [] })
    })

    test.each([
        [
            'a carried generated tool',
            [GENERATED],
            { [GENERATED]: generated('action-get', 'action-create', 'action-get') },
        ],
        [
            'a generated schema a carried tool reads',
            [SCHEMAS],
            { [SCHEMAS]: schemas({ ActionGet: 'a newer action', ActionCreate: 'a new action' }) },
        ],
    ])('needs a patch release for %s that hand-written code wraps', (_name, changed, head: Record<string, string>) => {
        const result = gaps(changed, head, {}, [[GENERATED, [REGISTRY, ALIASES]]])

        expect(result).toMatchObject({ needsRelease: true, bump: 'patch' })
        expect(result.reasons.map((reason) => reason.file)).toEqual(changed)
    })

    test.each(['@/generated//workflows/api', '@/generated/./workflows/api'])(
        'counts a schema change a hand-written tool reads through a second specifier for the same file, %s',
        (odd) => {
            const result = findCatalogGaps({
                changed: [SHARED_SCHEMAS],
                compiled: {
                    files: new Set([SHARED_SCHEMAS, HAND_WRITTEN_TOOL]),
                    importers: new Map([[SHARED_SCHEMAS, new Set([HAND_WRITTEN_TOOL])]]),
                    specifiers: new Map([
                        [SHARED_SCHEMAS, new Map([[HAND_WRITTEN_TOOL, ['@/generated/workflows/api', odd]]])],
                    ]),
                },
                readBase: (path) => ({ ...MODULES })[path],
                readHead: (path) =>
                    ({
                        [CATALOG_TOOLS_JSON]: CATALOG,
                        ...MODULES,
                        [SHARED_SCHEMAS]: schemas({ ...WORKFLOW_SCHEMAS, HogFlowsPartialUpdateParams: 'a new flow' }),
                        [HAND_WRITTEN_TOOL]: `import { WorkflowsGet } from '@/generated/workflows/api'\nimport { HogFlowsPartialUpdateParams } from '${odd}'\n`,
                    })[path],
            })

            expect(result.reasons.map((reason) => reason.file)).toEqual([SHARED_SCHEMAS])
        }
    )

    test('counts a schema change read by a tool the catalog build drops, though the tool list names it', () => {
        const result = findCatalogGaps({
            changed: [SCHEMAS],
            compiled: { files: new Set([GENERATED, SCHEMAS]), importers: new Map([[SCHEMAS, new Set([GENERATED])]]) },
            readBase: (path) => ({ ...MODULES })[path],
            readHead: (path) =>
                ({
                    [CATALOG_TOOLS_JSON]: CATALOG,
                    ...MODULES,
                    [SCHEMAS]: schemas({ ActionGet: 'a newer action', ActionCreate: 'a new action' }),
                })[path],
            carried: new Set(['action-create']),
        })

        expect(result.reasons).toEqual([
            expect.objectContaining({ file: SCHEMAS, why: expect.stringContaining('tools/generated/actions.ts') }),
        ])
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
    await mkdir(join(folder, 'services/mcp/src/lib'), { recursive: true })
    await writeFile(join(folder, 'services/mcp/src/lib/time:format.ts'), 'export const format = 1\n')
    await writeFile(
        metafile,
        JSON.stringify({
            inputs: {
                'src/cli/library.ts': {
                    imports: [
                        { path: '../../hog/src/version.ts', kind: 'import-statement', original: '@hog/version' },
                        { path: 'zod', external: true },
                        { path: '../../node_modules/.pnpm/zod/index.js' },
                    ],
                },
                '../../node_modules/.pnpm/zod/index.js': {},
                'dist/cli-library.mjs': {},
                '../../hog/src/version.ts': {},
                'src/lib/time:format.ts': {},
                'cf-stub:cloudflare:workers': {},
            },
        })
    )

    const { files, importers, specifiers } = compiledFiles(
        [{ path: metafile, root: join(folder, 'services/mcp') }],
        folder
    )

    expect([...files].sort()).toEqual([
        'hog/src/version.ts',
        'services/mcp/src/cli/library.ts',
        'services/mcp/src/lib/time:format.ts',
    ])
    expect(importers.get('hog/src/version.ts')).toEqual(new Set(['services/mcp/src/cli/library.ts']))
    expect(specifiers?.get('hog/src/version.ts')).toEqual(
        new Map([['services/mcp/src/cli/library.ts', ['@hog/version']]])
    )
})

test.each([
    ['unparseable', '{'],
    ['without inputs', JSON.stringify({ outputs: {} })],
    ['with no inputs', JSON.stringify({ inputs: {} })],
    ['missing', undefined],
])('fails on a metafile that is %s', async (_name, content) => {
    const folder = await mkdtemp(join(tmpdir(), 'hog-metafile-'))
    const metafile = join(folder, 'meta.json')
    if (content !== undefined) {
        await writeFile(metafile, content)
    }

    expect(() => compiledFiles([{ path: metafile, root: folder }], folder)).toThrow(metafile)
})

test('reads a file larger than the default subprocess buffer, and only a missing path as missing', async () => {
    const repo = await mkdtemp(join(tmpdir(), 'hog-git-'))
    const git = (...args: string[]): void => {
        execFileSync('git', ['-c', 'user.name=hog', '-c', 'user.email=hog@example.com', ...args], { cwd: repo })
    }
    const definitions = JSON.stringify({ 'exec-tool': { summary: 'x'.repeat(2 * 1024 * 1024) } })
    git('init', '-q')
    await writeFile(join(repo, 'tool-definitions.json'), definitions)
    git('add', '.')
    git('-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'definitions')

    const read = readAt(repo)

    expect(read('HEAD')('tool-definitions.json')).toBe(definitions)
    expect(read('HEAD')('missing.json')).toBeUndefined()
    expect(() => read('no-such-commit')('tool-definitions.json')).toThrow()
})

test('lists compiled files the release build checkout leaves out', () => {
    const workflow = [
        'jobs:',
        '    build:',
        '        steps:',
        '            - uses: actions/checkout@0000000000000000000000000000000000000000',
        '              with:',
        '                  sparse-checkout: |',
        '                      /*',
        '                      !/*/',
        '                      /hog/',
        '                      /products/notebooks/',
        '                      !/products/notebooks/frontend/',
        '                      /products/product_analytics/mcp/',
        '            - run: bun test',
    ].join('\n')
    const compiled = new Set([
        'package.json',
        'hog/src/cli.ts',
        'products/notebooks/notebook-widget-catalog.json',
        'products/notebooks/frontend/widget.ts',
        'products/product_analytics/mcp/apps/chart.ts',
        'products/error_tracking/mcp/tools.ts',
        'services/mcp/src/cli/library.ts',
    ])

    expect(outsideCheckout(compiled, releaseCheckoutPatterns(workflow))).toEqual([
        'products/notebooks/frontend/widget.ts',
        'products/error_tracking/mcp/tools.ts',
        'services/mcp/src/cli/library.ts',
    ])
})

test('lists compiled files the workflow trigger paths miss', () => {
    const workflow = [
        'on:',
        '    pull_request:',
        '        paths:',
        "            - 'hog/**'",
        "            - 'products/*/mcp/**'",
        "            - 'products/notebooks/*'",
        "            - '!products/notebooks/*.md'",
    ].join('\n')
    const compiled = new Set([
        'hog/src/cli.ts',
        'products/product_analytics/mcp/apps/chart.ts',
        'products/notebooks/notebook-widget-catalog.json',
        'products/notebooks/README.md',
        'products/notebooks/frontend/widget.ts',
    ])

    expect(untriggeredFiles(compiled, workflow)).toEqual([
        'products/notebooks/README.md',
        'products/notebooks/frontend/widget.ts',
    ])
})

test('lists the files the release paths of the approver check miss', () => {
    const paths = ['hog', ':(glob)products/*/mcp/**', 'pnpm-lock.yaml']

    expect(
        outsideReleasePaths(
            [
                'hog/src/cli.ts',
                'hogwarts/spell.ts',
                'products/surveys/mcp/tools.yaml',
                'products/surveys/backend/api.py',
                'pnpm-lock.yaml',
            ],
            paths
        )
    ).toEqual(['hogwarts/spell.ts', 'products/surveys/backend/api.py'])
})

test('lists the release build inputs the release paths miss', () => {
    const workflow = [
        'env:',
        '    HOG_SOURCE_PATHS: >-',
        '        hog',
        '        packages/quill',
        '        pnpm-lock.yaml',
        'jobs:',
        '    build:',
        '        steps:',
        '            - uses: actions/checkout@0000000000000000000000000000000000000000',
        '              with:',
        '                  sparse-checkout: |',
        '                      /*',
        '                      !/*/',
        '                      /hog/',
        '                      /products/surveys/mcp/',
        '                      /bin/fix-rdkafka-paths',
        '            - uses: ./.github/actions/pnpm-install',
    ].join('\n')
    const paths = ['hog', ':(glob)products/*/mcp/**', 'pnpm-lock.yaml', '.github/actions/pnpm-install']

    expect(outsideReleasePaths(releaseBuildInputs(workflow), paths)).toEqual([
        'bin/fix-rdkafka-paths',
        'packages/quill',
        '.github/workflows/release-hog.yml',
    ])
})
