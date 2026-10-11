import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-sdk-package-'))
const run = (command, args, cwd = temporary) =>
    execFileSync(command, args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
try {
    const packed = JSON.parse(
        run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', temporary], root)
    )[0]
    const files = new Set(packed.files.map(({ path }) => path))
    for (const expected of [
        'README.md',
        'AGENTS.md',
        'catalog.json',
        'coverage.json',
        'src/generated/feature-flags/archive.ts',
        'dist/generated/feature-flags/archive.d.ts',
        'dist/cli.js',
        'dist/agent-help.md',
        'dist/generated/handlers.mjs',
        'src/generated/notebooks/notebooks-create-markdown.ts',
    ]) {
        assert.ok(files.has(expected), `Missing ${expected}`)
    }
    await fs.writeFile(path.join(temporary, 'package.json'), JSON.stringify({ private: true, type: 'module' }))
    run('npm', ['install', '--ignore-scripts', '--no-audit', '--no-fund', path.join(temporary, packed.filename)])
    const script = `
import assert from 'node:assert/strict'
globalThis.fetch = () => assert.fail('discovery/import must not call the API')
const { default: defaultClient, client, createPostHogClient } = await import('@posthog/sdk')
assert.equal(defaultClient, client)
const { searchTools, describeTool } = await import('@posthog/sdk/discovery')
assert.equal(searchTools('archive feature flag')[0].method, 'featureFlags.archive')
const tool = describeTool('featureFlags.archive')
const { readFileSync } = await import('node:fs')
const root = new URL('./node_modules/@posthog/sdk/', import.meta.url)
assert.match(readFileSync(new URL(tool.input.source, root), 'utf8'), /export interface FeatureFlagsArchiveInput/)
const api = createPostHogClient({ env: false, token: 'phx_example', projectId: 1, fetch: async () => Response.json({ id: 17, key: 'example', status: 'ARCHIVED' }) })
assert.equal((await api.featureFlags.archive({ id: 17 })).data.id, 17)
const notebooks = createPostHogClient({ env: false, token: 'phx_example', projectId: 1, fetch: async () => Response.json({ short_id: 'sampleNotebook' }) })
assert.equal((await notebooks.notebooks.notebooksCreateMarkdown({ title: 'Sample report' })).data.notebook_id, 'sampleNotebook')
`
    await fs.writeFile(path.join(temporary, 'smoke.mjs'), script)
    run(process.execPath, ['smoke.mjs'])
    const list = run(process.execPath, ['node_modules/@posthog/sdk/dist/cli.js', 'list', '--json'])
    assert.ok(JSON.parse(list).tools.some(({ method }) => method === 'queries.sql'))
    const guide = run('npx', ['@posthog/sdk', '--agent-help'])
    assert.match(guide, /^# PostHog SDK guide for agents/)
    assert.match(guide, /`client\.queries\.sql`/)
    const consumer = `
import client, { type FeatureFlagsArchiveOutput, type QueriesTrendsInput } from '@posthog/sdk'
import type { FeatureFlagsArchiveInput } from '@posthog/sdk/feature-flags'
import type { QueriesSqlOutput } from '@posthog/sdk/queries'
import { describeTool } from '@posthog/sdk/discovery'
const input: FeatureFlagsArchiveInput = { id: 17 }
const result: Promise<FeatureFlagsArchiveOutput> = client.featureFlags.archive(input)
const notebook: Promise<{ data: { notebook_id: string; title: string } }> = client.notebooks.notebooksCreateMarkdown({ title: 'Sample report' })
// @ts-expect-error A custom MCP validator's required title remains required in the SDK.
client.notebooks.notebooksCreateMarkdown({})
const query: QueriesTrendsInput = { series: [{ kind: 'EventsNode', event: 'example_event' }] }
function read(output: QueriesSqlOutput): void {
    if (output.data.state === 'complete') console.log(output.data.result.results)
    if (output.data.state === 'pending') console.log(output.data.queryStatus.id)
}
// @ts-expect-error Identifiers are numbers, not numeric strings.
client.featureFlags.archive({ id: '17' })
// @ts-expect-error Completed-only results must be narrowed by state.
function invalid(output: QueriesSqlOutput): void { console.log(output.data.result) }
void [result, notebook, query, read, describeTool]
`
    await fs.writeFile(path.join(temporary, 'consumer.ts'), consumer)
    await fs.writeFile(
        path.join(temporary, 'tsconfig.json'),
        JSON.stringify({
            compilerOptions: {
                strict: true,
                noEmit: true,
                target: 'ES2022',
                module: 'NodeNext',
                types: [],
                skipLibCheck: false,
            },
            files: ['consumer.ts'],
        })
    )
    const require = createRequire(import.meta.url)
    run(process.execPath, [require.resolve('typescript/bin/tsc'), '-p', 'tsconfig.json'])
    process.stdout.write(
        `Validated installed @posthog/sdk: ${packed.files.length} files, ${packed.size} packed bytes, offline discovery and strict consumer types.\n`
    )
} finally {
    await fs.rm(temporary, { recursive: true, force: true })
}
