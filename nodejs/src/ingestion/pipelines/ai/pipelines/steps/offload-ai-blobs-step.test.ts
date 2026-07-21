import { Message } from 'node-rdkafka'

import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { PipelineResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { isOkResult } from '~/ingestion/framework/results'
import { BlobStore, EnsureStoredOutcome } from '~/ingestion/pipelines/ai/blob-offload/blob-store'
import { parseBlobPointer } from '~/ingestion/pipelines/ai/blob-offload/pointer'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { Team } from '~/types'

import {
    OffloadAiBlobsConfig,
    createExtractAiBlobsStep,
    createUploadAiBlobStep,
    extractAiBlobsFanOut,
    mergeAiBlobPointersFanIn,
} from './offload-ai-blobs-step'

const PNG_BYTES = Buffer.alloc(20000, 7)
const PNG_B64 = PNG_BYTES.toString('base64')

type ImageParts = { image_url: { url: string } }[]

type Input = { normalizedEvent: PluginEvent; team: Team }

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

function makeInput(properties: Record<string, unknown>): Input {
    return {
        normalizedEvent: createTestPluginEvent({ event: '$ai_generation', team_id: 2, properties }),
        team: createTestTeam({ id: 2 }),
    }
}

const CONFIG = { isTeamEnabled: (teamId: number): boolean => teamId === 2, minBase64Length: 8192, maxBlobsPerEvent: 50 }

/** The same extract → fanOutFanIn(upload) → merge wiring the AI pipeline uses. */
function createOffloadPipeline(store: BlobStore | null, config: OffloadAiBlobsConfig) {
    return newChunkPipelineBuilder<Input, { message: Message }>()
        .sequentially((b) => b.pipe(createExtractAiBlobsStep(store, config)))
        .fanOutFanIn(
            extractAiBlobsFanOut,
            (sub) => sub.concurrently((b) => b.pipe(createUploadAiBlobStep(store))),
            mergeAiBlobPointersFanIn
        )
        .build()
}

async function runOffload(
    store: FakeBlobStore | null,
    config: OffloadAiBlobsConfig,
    input: Input
): Promise<PipelineResultWithContext<Input, { message: Message }>> {
    const pipeline = createOffloadPipeline(store, config)
    pipeline.feed([createOkContext(input, { message: createTestMessage() })])
    const results: PipelineResultWithContext<Input, { message: Message }>[] = []
    let chunk = await pipeline.next()
    while (chunk !== null) {
        results.push(...chunk)
        chunk = await pipeline.next()
    }
    expect(results).toHaveLength(1)
    return results[0]
}

function okEvent(result: PipelineResultWithContext<Input, { message: Message }>): PluginEvent {
    if (!isOkResult(result.result)) {
        throw new Error('expected ok result')
    }
    return result.result.value.normalizedEvent
}

describe('offloadAiBlobs stage', () => {
    it('offloads binary from heavy props and rewrites them with pointers', async () => {
        const store = new FakeBlobStore()
        const input = makeInput({
            $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }],
            $ai_model: 'gpt-9',
        })
        const result = await runOffload(store, CONFIG, input)
        expect(store.stored).toHaveLength(1)
        expect(store.stored[0].teamId).toBe(2)
        expect(store.stored[0].bytes.equals(PNG_BYTES)).toBe(true)
        const props = okEvent(result).properties!
        const url = (props.$ai_input as ImageParts)[0].image_url.url
        expect(parseBlobPointer(url)?.hash).toBe(store.stored[0].hash)
        expect(props.$ai_model).toBe('gpt-9')
        // original event untouched
        expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url.startsWith('data:')).toBe(
            true
        )
    })

    it.each([
        [
            'team not enabled',
            new FakeBlobStore(),
            { isTeamEnabled: (): boolean => false, minBase64Length: 8192, maxBlobsPerEvent: 50 },
        ],
        ['store not configured', null, CONFIG],
    ])('passes through untouched when %s', async (_name, store, config) => {
        const input = makeInput({ $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }] })
        const result = await runOffload(store, config, input)
        expect(okEvent(result)).toBe(input.normalizedEvent)
        if (store) {
            expect(store.stored).toHaveLength(0)
        }
    })

    it('passes through text-only events without touching properties', async () => {
        const store = new FakeBlobStore()
        const input = makeInput({ $ai_input: [{ role: 'user', content: 'just text' }] })
        const result = await runOffload(store, CONFIG, input)
        expect(okEvent(result)).toBe(input.normalizedEvent)
        expect(store.stored).toHaveLength(0)
    })

    it('rejects (leaving the event unmodified) when storage fails', async () => {
        const store = new FakeBlobStore()
        store.failWith = new Error('s3 down')
        const input = makeInput({ $ai_input: [{ image_url: { url: `data:image/png;base64,${PNG_B64}` } }] })
        await expect(runOffload(store, CONFIG, input)).rejects.toThrow('s3 down')
        expect((input.normalizedEvent.properties!.$ai_input as ImageParts)[0].image_url.url.startsWith('data:')).toBe(
            true
        )
    })

    it.each([
        ['at the limit', 2, 2],
        ['over the limit', 3, 0],
    ])('enforces the per-event distinct blob limit (%s)', async (_name, blobCount, expectedStored) => {
        const store = new FakeBlobStore()
        const parts = Array.from({ length: blobCount }, (_, i) => ({
            image_url: { url: `data:image/png;base64,${Buffer.alloc(8192, i).toString('base64')}` },
        }))
        const input = makeInput({ $ai_input: parts })
        const result = await runOffload(store, { ...CONFIG, maxBlobsPerEvent: 2 }, input)
        expect(store.stored).toHaveLength(expectedStored)
        if (expectedStored === 0) {
            expect(okEvent(result)).toBe(input.normalizedEvent)
        }
    })

    it('deduplicates identical blobs across multiple heavy props', async () => {
        const store = new FakeBlobStore()
        const imageUrl = `data:image/png;base64,${PNG_B64}`
        const input = makeInput({
            $ai_input: [{ image_url: { url: imageUrl } }],
            $ai_output: [{ image_url: { url: imageUrl } }],
        })
        const result = await runOffload(store, CONFIG, input)
        expect(store.stored).toHaveLength(1)
        const storedHash = store.stored[0].hash
        const props = okEvent(result).properties!
        const inputUrl = (props.$ai_input as ImageParts)[0].image_url.url
        const outputUrl = (props.$ai_output as ImageParts)[0].image_url.url
        expect(parseBlobPointer(inputUrl)?.hash).toBe(storedHash)
        expect(parseBlobPointer(outputUrl)?.hash).toBe(storedHash)
    })
})
