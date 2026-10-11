import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog sdk package '))
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
        'api-index.tsv',
        'domains.tsv',
        'coverage.json',
        'src/generated/api.ts',
        'dist/generated/api.d.ts',
        'dist/cli.js',
        'dist/agent-help.md',
        'dist/generated/handlers.mjs',
        'dist/generated/notebooks/client.js',
    ]) {
        assert.ok(files.has(expected), `Missing ${expected}`)
    }
    await fs.writeFile(path.join(temporary, 'package.json'), JSON.stringify({ private: true, type: 'module' }))
    run('npm', ['install', '--ignore-scripts', '--no-audit', '--no-fund', path.join(temporary, packed.filename)])
    await fs.copyFile(
        new URL('../tests/fixtures/track-imports.mjs', import.meta.url),
        path.join(temporary, 'track-imports.mjs')
    )
    const script = `
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import { register } from 'node:module'
import { fileURLToPath } from 'node:url'
const logPath = new URL('./imports.log', import.meta.url)
writeFileSync(logPath, '')
register('./track-imports.mjs', import.meta.url, { data: { logPath: fileURLToPath(logPath) } })
const importedProducts = () => readFileSync(logPath, 'utf8').split('\\n').filter((url) => /\\/dist\\/generated\\/[^/]+\\/client\\.js$/.test(url))
globalThis.fetch = () => assert.fail('discovery/import must not call the API')
const { default: defaultClient, client, createPostHogClient } = await import('@posthog/sdk')
assert.equal(defaultClient, client)
assert.deepEqual(importedProducts(), [])
const { operations, domains } = await import('@posthog/sdk/discovery')
assert.ok(operations.some(({ method }) => method === 'featureFlags.archive'))
assert.ok(domains.some(({ domain }) => domain === 'featureFlags'))
const root = new URL('./node_modules/@posthog/sdk/', import.meta.url)
assert.match(readFileSync(new URL('src/generated/api.ts', root), 'utf8'), /export interface FeatureFlagsArchiveInput/)
const api = createPostHogClient({ env: false, token: 'phx_example', projectId: 1, fetch: async () => Response.json({ id: 17, key: 'example', status: 'ARCHIVED' }) })
const flags = api.featureFlags
assert.equal(flags, api.featureFlags)
assert.deepEqual(importedProducts(), [])
const [primary, scoped] = await Promise.all([
    flags.archive({ id: 17 }),
    api.project(2).featureFlags.archive({ id: 17 }),
    assert.rejects(flags.archive({ id: 17 }, { signal: AbortSignal.abort() }), (error) => error.details.kind === 'aborted'),
])
assert.equal(primary.data.id, 17)
assert.equal(scoped.data.id, 17)
assert.deepEqual(importedProducts(), [new URL('dist/generated/feature-flags/client.js', root).href])
const notebooks = createPostHogClient({ env: false, token: 'phx_example', projectId: 1, fetch: async () => Response.json({ short_id: 'sampleNotebook' }) })
assert.equal((await notebooks.notebooks.notebooksCreateMarkdown({ title: 'Sample report' })).data.notebook_id, 'sampleNotebook')
assert.deepEqual(importedProducts().sort(), ['feature-flags', 'notebooks'].map((product) => new URL('dist/generated/' + product + '/client.js', root).href).sort())
`
    await fs.writeFile(path.join(temporary, 'smoke.mjs'), script)
    run(process.execPath, ['smoke.mjs'])
    const guide = run('npx', ['--no-install', '@posthog/sdk', '--agent-help'])
    assert.match(guide, /^# PostHog SDK guide for agents/)
    assert.match(guide, /`client\.queries\.sql`/)
    assert.match(guide, /- `signals`: \d+ methods/)
    const packageRoot = path.join(temporary, 'node_modules/@posthog/sdk')
    for (const file of ['src/generated/api.ts', 'api-index.tsv', 'domains.tsv']) {
        const installed = path.join(packageRoot, file)
        assert.ok(guide.includes(installed), `Help must locate installed ${file}`)
        await fs.access(installed)
    }
    const relocated = path.join(temporary, "moved package's directory")
    await fs.rename(packageRoot, relocated)
    const relocatedGuide = run(process.execPath, [path.join(relocated, 'dist/cli.js'), '--agent-help'])
    assert.ok(relocatedGuide.includes(path.join(relocated, 'src/generated/api.ts')))
    assert.ok(relocatedGuide.includes("package'\\''s directory"))
    await fs.rename(relocated, packageRoot)
    const consumer = `
import client, { type FeatureFlagsArchiveOutput, type QueriesTrendsInput } from '@posthog/sdk'
import type { FeatureFlagsArchiveInput } from '@posthog/sdk/feature-flags'
import type { QueriesSqlOutput } from '@posthog/sdk/queries'
import { operations } from '@posthog/sdk/discovery'
import type { SignalsScoutRunsListInput } from '@posthog/sdk/api'
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
const runs: SignalsScoutRunsListInput = { limit: 1 }
void [result, notebook, query, read, operations, runs]
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
