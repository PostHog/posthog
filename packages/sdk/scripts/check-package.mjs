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
        'api-index.tsv',
        'domains.tsv',
        'coverage.json',
        'src/generated/api.ts',
        'dist/generated/api.d.ts',
        'dist/cli.js',
        'dist/runtime/tool-library.mjs',
        'dist/generated/notebooks/client.js',
    ]) {
        assert.ok(files.has(expected), `Missing ${expected}`)
    }
    await fs.writeFile(path.join(temporary, 'package.json'), JSON.stringify({ private: true, type: 'module' }))
    run('npm', ['install', '--ignore-scripts', '--no-audit', '--no-fund', path.join(temporary, packed.filename)])
    // The consumer directory has no workspace links. Supply only hog's reference bundle for the parity tests.
    const cliDir = path.join(temporary, 'node_modules/@posthog/mcp/dist')
    await fs.mkdir(cliDir, { recursive: true })
    await fs.copyFile(
        new URL('../../../services/mcp/dist/cli-library.mjs', import.meta.url),
        path.join(cliDir, 'cli-library.mjs')
    )
    await fs.copyFile(new URL('../tests/client.test.mjs', import.meta.url), path.join(temporary, 'client.test.mjs'))
    run(process.execPath, ['--test', 'client.test.mjs'])
    const guide = run('npx', ['--no-install', '@posthog/sdk', '--agent-help'])
    assert.match(guide, /^# PostHog SDK guide for agents/)
    assert.match(guide, /queries\.sql/)
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
    await fs.rename(relocated, packageRoot)
    const consumer = `
import client, { type FeatureFlagsListOutput } from '@posthog/sdk'
import type { FeatureFlagsListInput } from '@posthog/sdk/feature-flags'
import { operations } from '@posthog/sdk/discovery'
const input: FeatureFlagsListInput = { limit: 10 }
const page: FeatureFlagsListOutput = await client.featureFlags.list(input)
const key: string = page.results[0].key
const link: string = page.results[0]._posthogUrl
// @ts-expect-error The limit is numeric.
await client.featureFlags.list({ limit: 'ten' })
// @ts-expect-error Tool values have no SDK HTTP envelope.
console.log(page.meta.status)
void [key, link, operations]
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
