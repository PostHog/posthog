import { afterAll, describe, expect, test } from 'bun:test'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { Worker, type ContainerKind } from '@/error-tracking/worker'

import golden from './golden/containers.json'
import { generateInput } from './inputs'

// Each golden comes from posthog-cli's own container code (cli/examples/hog_parity_oracle.rs). A
// mismatch here means hog would upload different bytes than posthog-cli, and PostHog would reject
// a re-upload of the same file with `content_hash_mismatch`.
describe('symbol set containers match posthog-cli byte for byte', () => {
    const worker = new Worker()
    const folder = mkdtempSync(join(tmpdir(), 'hog-containers-'))

    afterAll(async () => {
        await worker.close()
        rmSync(folder, { recursive: true, force: true })
    })

    test.each(
        golden.map(
            (testCase) =>
                [`${testCase.type} ${testCase.input.generator} ${testCase.input.size} bytes`, testCase] as const
        )
    )('%s', async (name, testCase) => {
        const payload = join(folder, name)
        writeFileSync(payload, generateInput(testCase.input as never))

        const container = await worker.wrap(payload, testCase.type as ContainerKind, null)

        rmSync(payload)
        expect(container.contentHash).toBe(testCase.hash)
    })
})
