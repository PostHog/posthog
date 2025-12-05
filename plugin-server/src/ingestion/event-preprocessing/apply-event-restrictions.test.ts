import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { dlq, drop, ok, redirect } from '../pipelines/results'
import { RoutingConfig, createApplyEventRestrictionsStep } from './apply-event-restrictions'

describe('createApplyEventRestrictionsStep', () => {
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager
    let routingConfig: RoutingConfig
    let step: ReturnType<typeof createApplyEventRestrictionsStep>

    beforeEach(() => {
        eventIngestionRestrictionManager = {
            shouldDropEvent: jest.fn().mockReturnValue(false),
            shouldRedirectToDlq: jest.fn().mockReturnValue(false),
            shouldForceOverflow: jest.fn().mockReturnValue(false),
            shouldSkipPerson: jest.fn().mockReturnValue(false),
        } as unknown as EventIngestionRestrictionManager

        routingConfig = {
            overflowTopic: 'overflow-topic',
            preservePartitionLocality: true,
            overflowEnabled: true,
        }

        step = createApplyEventRestrictionsStep(eventIngestionRestrictionManager, routingConfig)
    })

    describe('drop events', () => {
        it('returns drop when shouldDropEvent returns true', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'blocked-token',
                    distinct_id: 'user-123',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)

            const result = await step(input)

            expect(result).toEqual(drop('blocked_token'))
        })

        it('passes token and distinct_id correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                undefined,
                undefined
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

            expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                'session-123',
                undefined,
                undefined
            )
        })

        it('passes event_name correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    event: '$pageview',
                }),
            }

            await step(input)

            expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                '$pageview',
                undefined
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

            expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                undefined,
                'event-uuid-123'
            )
        })
    })

    describe('DLQ redirect', () => {
        it('returns dlq when shouldRedirectToDlq returns true', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'dlq-token',
                    distinct_id: 'user-123',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)

            const result = await step(input)

            expect(result).toEqual(dlq('restricted_to_dlq'))
        })

        it('passes token and distinct_id correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldRedirectToDlq).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                undefined,
                undefined
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
            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldRedirectToDlq).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                'session-123',
                undefined,
                undefined
            )
        })

        it('passes event_name correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    event: '$pageview',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldRedirectToDlq).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                '$pageview',
                undefined
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
            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldRedirectToDlq).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                undefined,
                'event-uuid-123'
            )
        })
    })

    describe('overflow redirect', () => {
        it('returns redirect when shouldForceOverflow returns true', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'overflow-token',
                    distinct_id: 'user-123',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

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

        it('passes token and distinct_id correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                undefined,
                undefined
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
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                'session-123',
                undefined,
                undefined
            )
        })

        it('passes event_name correctly', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'test-user',
                    event: '$pageview',
                }),
            }
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                '$pageview',
                undefined
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
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            await step(input)

            expect(eventIngestionRestrictionManager.shouldForceOverflow).toHaveBeenCalledWith(
                'test-token',
                'test-user',
                undefined,
                undefined,
                'event-uuid-123'
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

            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

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

            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(false)

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

            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

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

            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldSkipPerson).mockReturnValue(true)

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

            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            const result = await disabledStep(input)

            expect(result).toEqual(ok(input))
            expect(eventIngestionRestrictionManager.shouldForceOverflow).not.toHaveBeenCalled()
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

            jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)

            const result = await step(input)

            expect(result).toEqual(drop('blocked_token'))
            expect(eventIngestionRestrictionManager.shouldRedirectToDlq).not.toHaveBeenCalled()
        })

        it('drop takes priority over overflow', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'token',
                    distinct_id: 'user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.shouldDropEvent).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            const result = await step(input)

            expect(result).toEqual(drop('blocked_token'))
            expect(eventIngestionRestrictionManager.shouldForceOverflow).not.toHaveBeenCalled()
        })

        it('DLQ takes priority over overflow', async () => {
            const input = {
                message: {} as any,
                headers: createTestEventHeaders({
                    token: 'token',
                    distinct_id: 'user',
                }),
            }

            jest.mocked(eventIngestionRestrictionManager.shouldRedirectToDlq).mockReturnValue(true)
            jest.mocked(eventIngestionRestrictionManager.shouldForceOverflow).mockReturnValue(true)

            const result = await step(input)

            expect(result).toEqual(dlq('restricted_to_dlq'))
            expect(eventIngestionRestrictionManager.shouldForceOverflow).not.toHaveBeenCalled()
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
            expect(eventIngestionRestrictionManager.shouldDropEvent).toHaveBeenCalledWith(
                undefined,
                undefined,
                undefined,
                undefined,
                undefined
            )
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
