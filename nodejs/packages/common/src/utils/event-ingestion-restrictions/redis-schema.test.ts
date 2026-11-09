import { RedisRestrictionArraySchema, RedisRestrictionItemSchema, toRestrictionRule } from './redis-schema'
import { RestrictionType } from './rules'

describe('RedisRestrictionItemSchema', () => {
    describe('v2 format parsing', () => {
        it('parses valid v2 format with all fields', () => {
            const input = {
                version: 2,
                token: 'test-token',
                pipelines: ['analytics'],
                distinct_ids: ['user1', 'user2'],
                session_ids: ['session1'],
                event_names: ['$pageview'],
                event_uuids: ['uuid-123'],
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(true)
            expect(result.data).toEqual(input)
        })

        it('allows missing filter fields (undefined)', () => {
            const input = {
                version: 2,
                token: 'test-token',
                pipelines: ['analytics'],
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(true)
            expect(result.data).toEqual({
                version: 2,
                token: 'test-token',
                pipelines: ['analytics'],
            })
        })
    })

    describe('v0 format parsing', () => {
        it('parses v0 format with explicit version: 0', () => {
            const input = {
                version: 0,
                token: 'test-token',
                pipelines: ['analytics'],
                distinct_id: 'user1',
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(true)
            expect(result.data).toEqual(input)
        })

        it('normalizes missing version to 0', () => {
            const input = {
                token: 'test-token',
                pipelines: ['analytics'],
                distinct_id: 'user1',
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(true)
            expect(result.data).toEqual({
                ...input,
                version: 0,
            })
        })

        it('parses v0 format with all single identifier fields', () => {
            const input = {
                token: 'test-token',
                pipelines: ['session_recordings'],
                distinct_id: 'user1',
                session_id: 'session1',
                event_name: '$snapshot',
                event_uuid: 'uuid-456',
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(true)
            expect(result.data?.version).toBe(0)
        })
    })

    describe('validation errors', () => {
        it('rejects missing token', () => {
            const input = {
                version: 2,
                pipelines: ['analytics'],
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(false)
        })

        it('rejects invalid pipeline value', () => {
            const input = {
                version: 2,
                token: 'test-token',
                pipelines: ['invalid_pipeline'],
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(false)
        })

        it('rejects invalid version', () => {
            const input = {
                version: 99,
                token: 'test-token',
            }

            const result = RedisRestrictionItemSchema.safeParse(input)

            expect(result.success).toBe(false)
        })
    })
})

describe('RedisRestrictionArraySchema', () => {
    it('parses array of mixed v0 and v2 entries', () => {
        const input = [
            { version: 2, token: 'token1', pipelines: ['analytics'], distinct_ids: ['u1'] },
            { token: 'token2', pipelines: ['analytics'], distinct_id: 'u2' }, // v0 without version
        ]

        const result = RedisRestrictionArraySchema.safeParse(input)

        expect(result.success).toBe(true)
        expect(result.data).toHaveLength(2)
        expect(result.data?.[0].version).toBe(2)
        expect(result.data?.[1].version).toBe(0)
    })

    it('parses empty array', () => {
        const result = RedisRestrictionArraySchema.safeParse([])

        expect(result.success).toBe(true)
        expect(result.data).toEqual([])
    })
})

describe('toRestrictionRule', () => {
    describe('v2 format conversion', () => {
        it('creates filtered scope when arrays have values', () => {
            const item = {
                version: 2 as const,
                token: 'test-token',
                pipelines: ['analytics' as const],
                distinct_ids: ['user1', 'user2'],
                session_ids: [],
                event_names: ['$pageview'],
                event_uuids: [],
            }

            const rule = toRestrictionRule(item, RestrictionType.DROP_EVENT)

            expect(rule.restrictionType).toBe(RestrictionType.DROP_EVENT)
            expect(rule.scope.type).toBe('filtered')
            if (rule.scope.type === 'filtered') {
                expect(rule.scope.filters.distinctIds).toEqual(new Set(['user1', 'user2']))
                expect(rule.scope.filters.eventNames).toEqual(new Set(['$pageview']))
                expect(rule.scope.filters.sessionIds.size).toBe(0)
                expect(rule.scope.filters.eventUuids.size).toBe(0)
            }
        })

        it('creates "all" scope when all arrays are empty', () => {
            const item = {
                version: 2 as const,
                token: 'test-token',
                pipelines: ['analytics' as const],
                distinct_ids: [],
                session_ids: [],
                event_names: [],
                event_uuids: [],
            }

            const rule = toRestrictionRule(item, RestrictionType.SKIP_PERSON_PROCESSING)

            expect(rule.restrictionType).toBe(RestrictionType.SKIP_PERSON_PROCESSING)
            expect(rule.scope.type).toBe('all')
        })

        it('creates "all" scope when filter arrays are undefined', () => {
            const item = {
                version: 2 as const,
                token: 'test-token',
                pipelines: ['analytics' as const],
            }

            const rule = toRestrictionRule(item, RestrictionType.SKIP_PERSON_PROCESSING)

            expect(rule.restrictionType).toBe(RestrictionType.SKIP_PERSON_PROCESSING)
            expect(rule.scope.type).toBe('all')
        })
    })

    describe('v0 format conversion', () => {
        it('creates filtered scope with single identifier', () => {
            const item = {
                version: 0 as const,
                token: 'test-token',
                pipelines: ['analytics' as const],
                distinct_id: 'user1',
            }

            const rule = toRestrictionRule(item, RestrictionType.FORCE_OVERFLOW)

            expect(rule.restrictionType).toBe(RestrictionType.FORCE_OVERFLOW)
            expect(rule.scope.type).toBe('filtered')
            if (rule.scope.type === 'filtered') {
                expect(rule.scope.filters.distinctIds).toEqual(new Set(['user1']))
            }
        })

        it('creates "all" scope when no identifiers present', () => {
            const item = {
                version: 0 as const,
                token: 'test-token',
                pipelines: ['analytics' as const],
            }

            const rule = toRestrictionRule(item, RestrictionType.REDIRECT_TO_DLQ)

            expect(rule.restrictionType).toBe(RestrictionType.REDIRECT_TO_DLQ)
            expect(rule.scope.type).toBe('all')
        })

        it('converts all v0 identifier fields to single-element sets', () => {
            const item = {
                version: 0 as const,
                token: 'test-token',
                pipelines: ['analytics' as const],
                distinct_id: 'user1',
                session_id: 'session1',
                event_name: '$pageview',
                event_uuid: 'uuid-123',
            }

            const rule = toRestrictionRule(item, RestrictionType.DROP_EVENT)

            expect(rule.scope.type).toBe('filtered')
            if (rule.scope.type === 'filtered') {
                expect(rule.scope.filters.distinctIds).toEqual(new Set(['user1']))
                expect(rule.scope.filters.sessionIds).toEqual(new Set(['session1']))
                expect(rule.scope.filters.eventNames).toEqual(new Set(['$pageview']))
                expect(rule.scope.filters.eventUuids).toEqual(new Set(['uuid-123']))
            }
        })
    })
})
