import { InMemoryLlmBlobStore } from './llm-blob-store'
import { compactCompletionForState, llmResultBlobKey } from './llm-spill'
import { LlmStepRequest } from './llm-step.types'

const REQUEST: Pick<LlmStepRequest, 'teamId' | 'jobId' | 'actionId' | 'nonce'> = {
    teamId: 7,
    jobId: 'job1',
    actionId: 'a1',
    nonce: 'n1',
}

describe('compactCompletionForState', () => {
    it('inlines a completion that fits within the threshold', async () => {
        const blobStore = new InMemoryLlmBlobStore()
        const completion = { text: 'short answer', model: 'gpt-4o-mini' }

        const out = await compactCompletionForState({
            completion,
            request: REQUEST as LlmStepRequest,
            blobStore,
            thresholdBytes: 8192,
        })

        expect(out).toEqual(completion)
        expect(blobStore.blobs.size).toBe(0)
    })

    it('spills an oversized completion to object storage and returns only a reference', async () => {
        const blobStore = new InMemoryLlmBlobStore()
        const bigText = 'x'.repeat(20_000)
        const completion = { text: bigText, parsed: { huge: bigText }, model: 'gpt-4o-mini' }

        const out = await compactCompletionForState({
            completion,
            request: REQUEST as LlmStepRequest,
            blobStore,
            thresholdBytes: 8192,
        })

        // Only a compact reference is kept for state - not the full payload.
        const key = llmResultBlobKey(REQUEST)
        expect(out.ref).toBe(key)
        expect(out.truncated).toBe(true)
        expect(out.byteSize).toBeGreaterThan(8192)
        expect(out.text.length).toBeLessThan(bigText.length)
        expect(out.parsed).toBeUndefined() // dropped from state; available via ref

        // What lands in state must be small enough for the 5KB variable cap.
        expect(Buffer.byteLength(JSON.stringify(out), 'utf8')).toBeLessThan(5120)

        // The full completion is retrievable from object storage.
        const stored = JSON.parse(await blobStore.get(key))
        expect(stored.text).toBe(bigText)
        expect(stored.parsed).toEqual({ huge: bigText })
    })
})
