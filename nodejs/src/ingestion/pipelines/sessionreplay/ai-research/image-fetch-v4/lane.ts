import {
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4_RETRY_1H,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4_RETRY_1M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4_RETRY_10M,
} from '~/common/config/kafka-topics'
import { parseV4UrlRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import type { HostLimits, ImageFetchLane } from '~/servers/ingestion-session-replay-ml-image-fetch-server'

/** The v4 lane has its own frontier, delay tiers and consumer groups, so its jobs never mix with the v3 lane's. */
export const V4_IMAGE_FETCH_LANE: ImageFetchLane = {
    frontier: KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4,
    retry1m: KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4_RETRY_1M,
    retry10m: KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4_RETRY_10M,
    retry1h: KAFKA_SESSION_REPLAY_IMAGE_FETCH_V4_RETRY_1H,
    groupIdSetting: 'AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_GROUP_ID',
    acceptsRef: (ref) => parseV4UrlRef(ref) !== null,
    // The recorder sends no version header: a v4 reference names its own dataset and no v3 session key.
    sessionKeyed: false,
}

/** The v4 per registrable domain limits: a share of the v3 limits, at least one request at a time. */
export function v4HostLimits(v3: HostLimits, share: number): HostLimits {
    if (!(share > 0 && share <= 1)) {
        throw new Error(`AI_RESEARCH_REPLAY_V4_IMAGE_FETCH_HOST_BUDGET_SHARE must be in (0, 1], got ${share}`)
    }
    return {
        requestsPerSecond: v3.requestsPerSecond * share,
        burst: Math.max(1, Math.floor(v3.burst * share)),
        maxConcurrent: Math.max(1, Math.floor(v3.maxConcurrent * share)),
    }
}
