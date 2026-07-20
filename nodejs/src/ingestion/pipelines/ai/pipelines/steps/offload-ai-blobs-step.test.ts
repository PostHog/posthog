import { isOkResult } from '~/ingestion/framework/results'
import { BlobStore, EnsureStoredOutcome } from '~/ingestion/pipelines/ai/blob-offload/blob-store'
import { parseBlobPointer } from '~/ingestion/pipelines/ai/blob-offload/pointer'
import { aiBlobOffloadTextBytes } from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { Team } from '~/types'

import { createOffloadAiBlobsStep } from './offload-ai-blobs-step'

const PNG_BYTES = Buffer.alloc(20000, 7)
const PNG_B64 = PNG_BYTES.toString('base64')

type ImageParts = { image_url: { url: string } }[]

class FakeBlobStore implements BlobStore {
    stored: { teamId: number; hash: string; bytes: Buffer; mime: string }[] = []
    failWith: Error | null = null

    ensureStored(teamId: number, blob: { hash: string; bytes: Buffer; mime: string }): Promise<EnsureStoredOutcome> {
        if (this.failWith) {
            return Promise.reject(this.failWith)
        }
        this.stored.push({ teamId, ...blob })
        return Promise.resolve('uploaded')
    }
}

function makeInput(properties: Record<string, unknown>): { normalizedEvent: PluginEvent; team: Team } {
    return {
        normalizedEvent: createTestPluginEvent({ event: '$ai_generation', team_id: 2, properties }),
        team: createTestTeam({ id: 2 }),
    }
}

const CONFIG = { isTeamEnabled: (teamId: number): boolean => teamId === 2, minBase64Length: 8192 }

describe('offloadAiBlobsStep', () => {
    it('offloads binary from heavy props and rewrites them with pointers', async () => {
        const store = new FakeBlobStore()
        const step = createOffloadAiBlobsStep(store, CONFIG)
        const input = makeInput({
            $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }],
            $ai_model: 'gpt-9',
        })
        const result = await step(input)
        if (!isOkResult(result)) {
            throw new Error('expected ok result')
        }
        expect(store.stored).toHaveLength(1)
        expect(store.stored[0].teamId).toBe(2)
        expect(store.stored[0].bytes.equals(PNG_BYTES)).toBe(true)
        const props = result.value.normalizedEvent.properties!
        const url = (props.$ai_input as ImageParts)[0].image_url.url
        expect(parseBlobPointer(url)?.hash).toBe(store.stored[0].hash)
        expect(props.$ai_model).toBe('gpt-9')
        // original event untouched
        expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url.startsWith('data:')).toBe(
            true
        )
    })

    it.each([
        ['team not enabled', new FakeBlobStore(), { isTeamEnabled: (): boolean => false, minBase64Length: 8192 }],
        ['store not configured', null, CONFIG],
    ])('passes through untouched when %s', async (_name, store, config) => {
        const step = createOffloadAiBlobsStep(store, config)
        const input = makeInput({ $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }] })
        const result = await step(input)
        if (!isOkResult(result)) {
            throw new Error('expected ok result')
        }
        expect(result.value).toBe(input)
        if (store) {
            expect(store.stored).toHaveLength(0)
        }
    })

    it('passes through text-only events without touching properties', async () => {
        const store = new FakeBlobStore()
        const step = createOffloadAiBlobsStep(store, CONFIG)
        const input = makeInput({ $ai_input: [{ role: 'user', content: 'just text' }] })
        const result = await step(input)
        if (!isOkResult(result)) {
            throw new Error('expected ok result')
        }
        expect(result.value).toBe(input)
        expect(store.stored).toHaveLength(0)
    })

    it('records a text-size forecast observation for text-only heavy props', async () => {
        aiBlobOffloadTextBytes.reset()
        const store = new FakeBlobStore()
        const step = createOffloadAiBlobsStep(store, CONFIG)
        const input = makeInput({ $ai_input: [{ role: 'user', content: 'just text' }] })
        await step(input)
        const values = (await aiBlobOffloadTextBytes.get()).values
        const count = values.find((v) => v.metricName === 'aio_blob_offload_text_bytes_count')?.value ?? 0
        const sum = values.find((v) => v.metricName === 'aio_blob_offload_text_bytes_sum')?.value ?? 0
        expect(count).toBe(1)
        expect(sum).toBeGreaterThan(0)
    })

    it('rejects (leaving the event unmodified) when storage fails', async () => {
        const store = new FakeBlobStore()
        store.failWith = new Error('s3 down')
        const step = createOffloadAiBlobsStep(store, CONFIG)
        const input = makeInput({ $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }] })
        await expect(step(input)).rejects.toThrow('s3 down')
        expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url.startsWith('data:')).toBe(
            true
        )
    })

    it('deduplicates identical blobs across multiple heavy props', async () => {
        const store = new FakeBlobStore()
        const step = createOffloadAiBlobsStep(store, CONFIG)
        const imageUrl = `data:image/png;base64,${PNG_B64}`
        const input = makeInput({
            $ai_input: [{ image_url: { url: imageUrl } }],
            $ai_output: [{ image_url: { url: imageUrl } }],
        })
        const result = await step(input)
        if (!isOkResult(result)) {
            throw new Error('expected ok result')
        }
        expect(store.stored).toHaveLength(1)
        const storedHash = store.stored[0].hash
        const props = result.value.normalizedEvent.properties!
        const inputUrl = (props.$ai_input as ImageParts)[0].image_url.url
        const outputUrl = (props.$ai_output as ImageParts)[0].image_url.url
        expect(parseBlobPointer(inputUrl)?.hash).toBe(storedHash)
        expect(parseBlobPointer(outputUrl)?.hash).toBe(storedHash)
    })
})
