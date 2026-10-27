import {
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH,
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_RETRY_1H,
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_RETRY_1M,
    KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_RETRY_10M,
} from '~/common/config/kafka-topics'

/** The v4 lane has its own frontier, delay tiers and consumer groups, so its jobs never mix with the v3 lane's. */
export const V4_IMAGE_FETCH_LANE = {
    frontier: KAFKA_AI_RESEARCH_V4_IMAGE_FETCH,
    retry1m: KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_RETRY_1M,
    retry10m: KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_RETRY_10M,
    retry1h: KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_RETRY_1H,
} as const

/** The delay tiers the publisher writes to. A retry pod drains one of these and nothing else. */
export const V4_IMAGE_FETCH_DELAY_TOPICS: readonly string[] = [
    V4_IMAGE_FETCH_LANE.retry1m,
    V4_IMAGE_FETCH_LANE.retry10m,
    V4_IMAGE_FETCH_LANE.retry1h,
]

/** A dead letter must never land on a topic the lane consumes, which would loop it back. */
export const BLOCKED_IMAGE_FETCH_DEAD_LETTER_TOPICS: readonly string[] = [
    V4_IMAGE_FETCH_LANE.frontier,
    ...V4_IMAGE_FETCH_DELAY_TOPICS,
]

/** The v3 lane's default group. A v4 pod in it would take v3 partitions and read none of their topics. */
const V3_IMAGE_FETCH_GROUP_ID = 'session-replay-ml-image-fetch'

export function assertOwnImageFetchGroup(group: string): void {
    if (!group || group === V3_IMAGE_FETCH_GROUP_ID) {
        throw new Error('AI_RESEARCH_V4_IMAGE_FETCH_GROUP_ID must be set and differ from the v3 lane group')
    }
}

export interface HostLimits {
    requestsPerSecond: number
    burst: number
    maxConcurrent: number
}

/** The v4 per registrable domain limits: a share of the configured limits, at least one request at a time. */
export function v4HostLimits(limits: HostLimits, share: number): HostLimits {
    if (!(share > 0 && share <= 1)) {
        throw new Error(`AI_RESEARCH_V4_IMAGE_FETCH_HOST_BUDGET_SHARE must be in (0, 1], got ${share}`)
    }
    return {
        requestsPerSecond: limits.requestsPerSecond * share,
        burst: Math.max(1, Math.floor(limits.burst * share)),
        maxConcurrent: Math.max(1, Math.floor(limits.maxConcurrent * share)),
    }
}
