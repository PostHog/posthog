import { drop, ok } from '~/ingestion/framework/results'
import { createTestPipelineEvent } from '~/tests/helpers/pipeline-event'
import { PipelineEvent } from '~/types'

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

        it('drops $groupidentify with a group_key object whose toString is not callable', async () => {
            const groupKey = { toString: null, padding: 'a'.repeat(401) }
            const input = {
                event: createTestPipelineEvent({
                    event: '$groupidentify',
                    distinct_id: 'user123',
                    team_id: 1,
                    properties: { $group_key: groupKey },
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
                                groupKey,
                                groupKeyLength: 431,
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

    describe('group type validation', () => {
        const groupIdentify = (groupType: unknown): { event: PipelineEvent } => ({
            event: createTestPipelineEvent({
                event: '$groupidentify',
                distinct_id: 'user123',
                team_id: 1,
                properties: { $group_type: groupType, $group_key: 'org_1' },
            }),
        })

        it.each([
            ['a string longer than 400 characters', 'a'.repeat(401), 'a'.repeat(100), 401],
            [
                'an object whose JSON is longer than 400 characters',
                { blob: 'a'.repeat(400) },
                `{"blob":"${'a'.repeat(91)}`,
                411,
            ],
            [
                'an object whose toString is not callable',
                { toString: null, padding: 'a'.repeat(401) },
                `{"toString":null,"padding":"${'a'.repeat(72)}`,
                431,
            ],
        ])('drops $groupidentify with %s', async (_name, groupType, groupTypePreview, groupTypeLength) => {
            const input = groupIdentify(groupType)

            const result = await step(input)

            expect(result).toEqual(
                drop(
                    'group_type_too_long',
                    [],
                    [
                        {
                            type: 'group_type_too_long',
                            details: {
                                eventUuid: '123e4567-e89b-12d3-a456-426614174000',
                                event: '$groupidentify',
                                distinctId: 'user123',
                                groupKey: 'org_1',
                                groupType: groupTypePreview,
                                groupTypeLength,
                                maxLength: 400,
                            },
                        },
                    ]
                )
            )
        })

        it.each([
            ['exactly 400 characters', 'a'.repeat(400)],
            ['a number', 7],
            ['missing', undefined],
        ])('allows $groupidentify with group_type %s', async (_name, groupType) => {
            const input = groupIdentify(groupType)

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
