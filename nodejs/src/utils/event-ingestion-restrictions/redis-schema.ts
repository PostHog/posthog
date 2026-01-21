import { z } from 'zod'

import { RestrictionFilters, RestrictionRule, RestrictionType } from './rules'

// Redis key names for each restriction type
export enum RedisRestrictionType {
    DROP_EVENT_FROM_INGESTION = 'drop_event_from_ingestion',
    SKIP_PERSON_PROCESSING = 'skip_person_processing',
    FORCE_OVERFLOW_FROM_INGESTION = 'force_overflow_from_ingestion',
    REDIRECT_TO_DLQ = 'redirect_to_dlq',
}

export const REDIS_KEY_PREFIX = 'event_ingestion_restriction_dynamic_config'

// Base schema for common fields
const pipelinesSchema = z.array(z.enum(['analytics', 'session_recordings'])).optional()

// Redis schema v0 (legacy) - single identifier per entry, no version field
const RedisRestrictionItemSchemaV0 = z.object({
    version: z.literal(0),
    token: z.string(),
    pipelines: pipelinesSchema,
    distinct_id: z.string().optional(),
    session_id: z.string().optional(),
    event_name: z.string().optional(),
    event_uuid: z.string().optional(),
})

// Redis schema v2 - arrays per filter type (mirrors Rust format)
const RedisRestrictionItemSchemaV2 = z.object({
    version: z.literal(2),
    token: z.string(),
    pipelines: pipelinesSchema,
    distinct_ids: z.array(z.string()).optional(),
    session_ids: z.array(z.string()).optional(),
    event_names: z.array(z.string()).optional(),
    event_uuids: z.array(z.string()).optional(),
})

// Preprocess to normalize version: missing/undefined -> 0
const normalizeVersion = (data: unknown): unknown => {
    if (typeof data === 'object' && data !== null && !('version' in data)) {
        return { ...data, version: 0 }
    }
    return data
}

// Discriminated union on version field (0 for legacy v0, 2 for v2)
export const RedisRestrictionItemSchema = z.preprocess(
    normalizeVersion,
    z.discriminatedUnion('version', [RedisRestrictionItemSchemaV2, RedisRestrictionItemSchemaV0])
)

export type RedisRestrictionItem =
    | z.infer<typeof RedisRestrictionItemSchemaV2>
    | z.infer<typeof RedisRestrictionItemSchemaV0>

export const RedisRestrictionArraySchema = z.array(RedisRestrictionItemSchema)

// Convert a Redis entry to a RestrictionRule
export function toRestrictionRule(item: RedisRestrictionItem, restrictionType: RestrictionType): RestrictionRule {
    if (item.version === 2) {
        // V2 format - arrays
        const filters = new RestrictionFilters({
            distinctIds: item.distinct_ids,
            sessionIds: item.session_ids,
            eventNames: item.event_names,
            eventUuids: item.event_uuids,
        })
        return {
            restrictionType,
            scope: filters.isEmpty() ? { type: 'all' } : { type: 'filtered', filters },
        }
    } else {
        // V0 format (version === 0) - single identifier (creates single-element arrays)
        const filters = new RestrictionFilters({
            distinctIds: item.distinct_id ? [item.distinct_id] : [],
            sessionIds: item.session_id ? [item.session_id] : [],
            eventNames: item.event_name ? [item.event_name] : [],
            eventUuids: item.event_uuid ? [item.event_uuid] : [],
        })
        return {
            restrictionType,
            scope: filters.isEmpty() ? { type: 'all' } : { type: 'filtered', filters },
        }
    }
}
