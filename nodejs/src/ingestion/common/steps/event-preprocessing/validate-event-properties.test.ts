import { drop, ok } from '~/ingestion/framework/results'
import { createTestPipelineEvent } from '~/tests/helpers/pipeline-event'

import { createValidateEventPropertiesStep } from './validate-event-properties'

// Mock the dependencies
jest.mock('~/common/metrics', () => ({
    eventDroppedCounter: {
        labels: jest.fn().mockReturnThis(),
        inc: jest.fn(),
    },
}))

describe('createValidateEventPropertiesStep', () => {
    const step = createValidateEventPropertiesStep()

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('group identify validation', () => {
        it('should drop $groupidentify events with group_key longer than 400 characters', async () => {
            const longGroupKey = 'a'.repeat(401)
            const input = {
                event: createTestPipelineEvent({
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: {
                        $group_key: longGroupKey,
                    },
                }),
            }

            const result = await step(input)

            expect(result).toEqual(
                drop(
                    'group_key_too_long',
                    [],
                    [
                        {
                            type: 'group_key_too_long',
                            details: {
                                eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                event: '$groupidentify',
                                distinctId: 'user123',
                                groupKey: longGroupKey,
                                groupKeyLength: 401,
                                maxLength: 400,
                            },
                        },
                    ]
                )
            )
        })

        it('should allow $groupidentify events with group_key shorter than 400 characters', async () => {
            const shortGroupKey = 'a'.repeat(399)
            const input = {
                event: createTestPipelineEvent({
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: {
                        $group_key: shortGroupKey,
                    },
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow $groupidentify events with group_key exactly 400 characters', async () => {
            const exactGroupKey = 'a'.repeat(400)
            const input = {
                event: createTestPipelineEvent({
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: {
                        $group_key: exactGroupKey,
                    },
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow $groupidentify events without group_key', async () => {
            const input = {
                event: createTestPipelineEvent({
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: {},
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })

    describe('other event types', () => {
        it('should allow non-groupidentify events', async () => {
            const input = {
                event: createTestPipelineEvent({
                    distinct_id: 'user123',
                    team_id: 1,
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow regular events', async () => {
            const input = {
                event: createTestPipelineEvent({
                    event: 'button_clicked',
                    distinct_id: 'user123',
                    team_id: 1,
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })

    describe('identify/alias distinct-id validation', () => {
        it.each<{ desc: string; value: unknown; receivedType: string }>([
            { desc: 'a poisoned object ({ toString: null })', value: { toString: null }, receivedType: 'object' },
            { desc: 'a plain object', value: { foo: 'bar' }, receivedType: 'object' },
            { desc: 'an array', value: ['a', 'b'], receivedType: 'array' },
            { desc: 'a number', value: 42, receivedType: 'number' },
        ])(
            'should drop $identify with an invalid_anon_distinct_id warning when $anon_distinct_id is $desc',
            async ({ value, receivedType }) => {
                const input = {
                    event: createTestPipelineEvent({
                        event: '$identify',
                        distinct_id: 'user123',
                        team_id: 1,
                        properties: { $anon_distinct_id: value as any },
                    }),
                }

                const result = await step(input)

                expect(result).toEqual(
                    drop(
                        'invalid_anon_distinct_id',
                        [],
                        [
                            {
                                type: 'invalid_anon_distinct_id',
                                details: {
                                    eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                    event: '$identify',
                                    distinctId: 'user123',
                                    receivedType,
                                },
                            },
                        ]
                    )
                )
            }
        )

        it.each<{ event: string }>([{ event: '$create_alias' }, { event: '$merge_dangerously' }])(
            'should drop $event with an invalid_alias warning when alias is a poisoned object',
            async ({ event }) => {
                const input = {
                    event: createTestPipelineEvent({
                        event,
                        distinct_id: 'user123',
                        team_id: 1,
                        properties: { alias: { toString: null } as any },
                    }),
                }

                const result = await step(input)

                expect(result).toEqual(
                    drop(
                        'invalid_alias',
                        [],
                        [
                            {
                                type: 'invalid_alias',
                                details: {
                                    eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                    event,
                                    distinctId: 'user123',
                                    receivedType: 'object',
                                },
                            },
                        ]
                    )
                )
            }
        )

        it('should allow $identify with a valid string $anon_distinct_id', async () => {
            const input = {
                event: createTestPipelineEvent({
                    event: '$identify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: { $anon_distinct_id: 'anon-abc' },
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should allow an identify event with no $anon_distinct_id or alias', async () => {
            const input = {
                event: createTestPipelineEvent({
                    event: '$identify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: {},
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })
})
