import { logger } from '~/common/utils/logger'

import { JobBlobStore, buildJobBlobStore } from '../parked-jobs/blob-store'

// The LLM step spills large completions through the generic parked-job blob store. These are thin
// LLM-named aliases + the env wiring so the executor and its tests keep their imports.
export type LlmBlobStore = JobBlobStore
export {
    S3JobBlobStore as S3LlmBlobStore,
    InMemoryJobBlobStore as InMemoryLlmBlobStore,
} from '../parked-jobs/blob-store'

// Builds the LLM blob store from env, defaulting to the local SeaweedFS S3 endpoint. Returns null
// when object storage isn't configured — the executor then inlines completions.
export function buildLlmBlobStore(): LlmBlobStore | null {
    const store = buildJobBlobStore({
        endpoint: process.env.CDP_LLM_S3_ENDPOINT ?? 'http://localhost:8333',
        region: process.env.CDP_LLM_S3_REGION ?? 'us-east-1',
        bucket: process.env.CDP_LLM_S3_BUCKET ?? 'posthog',
        accessKeyId: process.env.CDP_LLM_S3_ACCESS_KEY_ID ?? 'any',
        secretAccessKey: process.env.CDP_LLM_S3_SECRET_ACCESS_KEY ?? 'any',
        timeoutMs: Number(process.env.CDP_LLM_S3_TIMEOUT_MS ?? 30_000),
    })
    if (!store) {
        logger.warn('⚠️', 'LLM object storage is not configured - large completions will not be spilled')
    }
    return store
}
