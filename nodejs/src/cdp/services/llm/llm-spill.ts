import { LlmBlobStore } from './llm-blob-store'
import { LlmStepCompletion, LlmStepRequest } from './llm-step.types'

// How much of the text to keep inline as a preview when a completion is spilled.
const PREVIEW_CHARS = 2000

export function llmResultBlobKey(request: Pick<LlmStepRequest, 'teamId' | 'jobId' | 'actionId' | 'nonce'>): string {
    return `llm-results/${request.teamId}/${request.jobId}/${request.actionId}/${request.nonce}.json`
}

// Keeps the completion that gets written into cyclotron_jobs.state small. If the serialized
// completion is within the threshold it's returned unchanged (inlined); otherwise the full payload
// is written to object storage and a compact reference (preview text + ref) is returned instead, so
// the parked row stays small no matter how large the model's output is.
export async function compactCompletionForState(args: {
    completion: LlmStepCompletion
    request: LlmStepRequest
    blobStore: LlmBlobStore
    thresholdBytes: number
}): Promise<LlmStepCompletion> {
    const { completion, request, blobStore, thresholdBytes } = args
    const serialized = JSON.stringify(completion)
    const byteSize = Buffer.byteLength(serialized, 'utf8')
    if (byteSize <= thresholdBytes) {
        return completion
    }

    const key = llmResultBlobKey(request)
    await blobStore.put(key, serialized)
    return {
        text: completion.text.length > PREVIEW_CHARS ? completion.text.slice(0, PREVIEW_CHARS) : completion.text,
        model: completion.model,
        usage: completion.usage,
        ref: key,
        byteSize,
        truncated: true,
        // `parsed` is intentionally dropped from state - it can be as large as the text. The full
        // completion (text + parsed) is at `ref`; a downstream step that needs it fetches by ref.
    }
}
