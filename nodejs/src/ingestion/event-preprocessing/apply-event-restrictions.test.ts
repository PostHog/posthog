import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager, Restriction } from '../../utils/event-ingestion-restriction-manager'
import { dlq, drop, ok, redirect } from '../pipelines/results'
import { RoutingConfig, createApplyEventRestrictionsStep } from './apply-event-restrictions'

describe('createApplyEventRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let routingConfig: RoutingConfig
    let step: ReturnType<typeof createApplyEventRestrictionsStep>

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            getAppliedRestrictions: jest.fn().mockReturnValue(new Set()),
        } as unknown as EventIngestionRestrictionManager

        routingConfig = {
            overflowTopic: 'overflow-topic',
            preservePartitionLocality: true,
            overflowEnabled: true,
        }

        step = createApplyEventRestrictionsStep(eventIngestionRestrictionManager, routingConfig)
    })

    describe('header passing', () => {
        it('passes token and distinct_id correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
                'test-token',
                expect.objectContaining({ distinct_id: 'test-user' })
            )
        })

        it('passes session_id correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    session_id: 'session-123',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
                'test-token',
                expect.objectContaining({ distinct_id: 'test-user', session_id: 'session-123' })
            )
        })

        it('passes event correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    event: '$pageview',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
                'test-token',
                expect.objectContaining({ distinct_id: 'test-user', event: '$pageview' })
            )
        })

        it('passes uuid correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    uuid: 'event-uuid-123',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
                'test-token',
                expect.objectContaining({ distinct_id: 'test-user', uuid: 'event-uuid-123' })
            )
        })

        it('passes all headers correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    session_id: 'session-123',
                    event: '$pageview',
                    uuid: 'event-uuid-123',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(
                'test-token',
                expect.objectContaining({
                    distinct_id: 'test-user',
                    session_id: 'session-123',
                    event: '$pageview',
                    uuid: 'event-uuid-123',
                })
            )
        })
    })

    describe('drop events', () => {
        it('returns drop when DROP_EVENT restriction is applied', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'blocked-token',
                    distinct_id: 'user-123',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.DROP_EVENT])
            )

            const result = await step(input)

            expect(result).toEqual(drop('blocked_token'))
        })
    })

    describe('DLQ redirect', () => {
        it('returns dlq when REDIRECT_TO_DLQ restriction is applied', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'dlq-token',
                    distinct_id: 'user-123',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.REDIRECT_TO_DLQ])
            )

            const result = await step(input)

            expect(result).toEqual(dlq('restricted_to_dlq'))
        })
    })

    describe('overflow redirect', () => {
        it('returns redirect when FORCE_OVERFLOW restriction is applied', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'overflow-token',
                    distinct_id: 'user-123',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            const result = await step(input)

            expect(result).toEqual(
                redirect(
                    'Event redirected to overflow due to force overflow restrictions',
                    'overflow-topic',
                    true,
                    false
                )
            )
        })

        it('partition locality: config=true, skipPerson=false -> preserves locality', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            const result = await step(input)

            expect(result).toEqual(
                redirect(
                    'Event redirected to overflow due to force overflow restrictions',
                    'overflow-topic',
                    true,
                    false
                )
            )
        })

        it('partition locality: config=false, skipPerson=false -> preserves locality', async () => {
            const configWithNoLocality: RoutingConfig = {
                ...routingConfig,
                preservePartitionLocality: false,
            }
            const stepWithNoLocality = createApplyEventRestrictionsStep(
                eventIngestionRestrictionManager,
                configWithNoLocality
            )

            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            const result = await stepWithNoLocality(input)

            expect(result).toEqual(
                redirect(
                    'Event redirected to overflow due to force overflow restrictions',
                    'overflow-topic',
                    true, // Always true when not skipping person, ignores config
                    false
                )
            )
        })

        it('partition locality: config=true, skipPerson=true -> preserves locality', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW, Restriction.SKIP_PERSON_PROCESSING])
            )

            const result = await step(input)

            expect(result).toEqual(
                redirect(
                    'Event redirected to overflow due to force overflow restrictions',
                    'overflow-topic',
                    true, // Uses config value
                    false
                )
            )
        })

        it('partition locality: config=false, skipPerson=true -> does not preserve locality', async () => {
            const configWithNoLocality: RoutingConfig = {
                ...routingConfig,
                preservePartitionLocality: false,
            }
            const stepWithNoLocality = createApplyEventRestrictionsStep(
                eventIngestionRestrictionManager,
                configWithNoLocality
            )

            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW, Restriction.SKIP_PERSON_PROCESSING])
            )

            const result = await stepWithNoLocality(input)

            expect(result).toEqual(
                redirect(
                    'Event redirected to overflow due to force overflow restrictions',
                    'overflow-topic',
                    false, // Uses config value
                    false
                )
            )
        })

        it('returns success when overflow is disabled', async () => {
            const disabledConfig: RoutingConfig = {
                ...routingConfig,
                overflowEnabled: false,
            }
            const disabledStep = createApplyEventRestrictionsStep(eventIngestionRestrictionManager, disabledConfig)

            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.FORCE_OVERFLOW])
            )

            const result = await disabledStep(input)

            expect(result).toEqual(ok(input))
        })
    })

    describe('priority ordering', () => {
        it('drop takes priority over DLQ', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'token',
                    distinct_id: 'user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.DROP_EVENT, Restriction.REDIRECT_TO_DLQ])
            )

            const result = await step(input)

            expect(result).toEqual(drop('blocked_token'))
        })

        it('drop takes priority over overflow', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'token',
                    distinct_id: 'user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.DROP_EVENT, Restriction.FORCE_OVERFLOW])
            )

            const result = await step(input)

            expect(result).toEqual(drop('blocked_token'))
        })

        it('DLQ takes priority over overflow', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'token',
                    distinct_id: 'user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.getAppliedRestrictions).mockReturnValue(
                new Set([Restriction.REDIRECT_TO_DLQ, Restriction.FORCE_OVERFLOW])
            )

            const result = await step(input)

            expect(result).toEqual(dlq('restricted_to_dlq'))
        })

        it('returns ok when nothing matches', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'token',
                    distinct_id: 'user',
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })

    describe('edge cases', () => {
        it('handles undefined headers', async () => {
            const input = {
                message: {} as any,
                headers: {} as EventHeaders,
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
            expect(eventIngestionRestrictionManager.getAppliedRestrictions).toHaveBeenCalledWith(undefined, {})
        })

        it('handles empty headers', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders(),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })
})
