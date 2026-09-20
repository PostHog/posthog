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

        // A non-string $group_key is caller-controlled and reaches String()/.toString() downstream,
        // which throws for a poisoned value ({ toString: null }) and crashes the consumer. Reject early.
        it.each<{ desc: string; groupKey: unknown; receivedType: string }>([
            { desc: 'a plain object', groupKey: { foo: 'bar' }, receivedType: 'object' },
            { desc: 'a poisoned object ({ toString: null })', groupKey: { toString: null }, receivedType: 'object' },
            { desc: 'an array', groupKey: ['a', 'b'], receivedType: 'array' },
            { desc: 'a number', groupKey: 42, receivedType: 'number' },
        ])(
            'should drop $groupidentify with an invalid_group_key warning when $group_key is $desc',
            async ({ groupKey, receivedType }) => {
                const input = {
                    event: createTestPipelineEvent({
                        event: '$groupidentify',
                        distinct_id: 'user123',
                        team_id: 1,
                        properties: { $group_key: groupKey as any },
                    }),
                }

                const result = await step(input)

                expect(result).toEqual(
                    drop(
                        'invalid_group_key',
                        [],
                        [
                            {
                                type: 'invalid_group_key',
                                details: {
                                    eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                    event: '$groupidentify',
                                    distinctId: 'user123',
                                    receivedType,
                                },
                            },
                        ]
                    )
                )
            }
        )

        it.each<{ desc: string; groupType: unknown; receivedType: string }>([
            { desc: 'a poisoned object ({ toString: null })', groupType: { toString: null }, receivedType: 'object' },
            { desc: 'an array', groupType: ['a'], receivedType: 'array' },
            { desc: 'a number', groupType: 7, receivedType: 'number' },
        ])(
            'should drop $groupidentify with an invalid_group_type warning when $group_type is $desc',
            async ({ groupType, receivedType }) => {
                const input = {
                    event: createTestPipelineEvent({
                        event: '$groupidentify',
                        distinct_id: 'user123',
                        team_id: 1,
                        properties: { $group_key: 'org::5', $group_type: groupType as any },
                    }),
                }

                const result = await step(input)

                expect(result).toEqual(
                    drop(
                        'invalid_group_type',
                        [],
                        [
                            {
                                type: 'invalid_group_type',
                                details: {
                                    eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                    event: '$groupidentify',
                                    distinctId: 'user123',
                                    receivedType,
                                },
                            },
                        ]
                    )
                )
            }
        )

        it('should allow $groupidentify with valid string $group_key and $group_type', async () => {
            const input = {
                event: createTestPipelineEvent({
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: { $group_key: 'org::5', $group_type: 'organization' },
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
})
