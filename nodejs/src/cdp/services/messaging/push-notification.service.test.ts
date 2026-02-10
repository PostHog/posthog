import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleInvocation, createHogFunction } from '~/cdp/_tests/fixtures'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'

import { HogInputsService } from '../hog-inputs.service'
import { PushSubscriptionsManagerService } from '../managers/push-subscriptions-manager.service'
import {
    PushNotificationFetchUtils,
    PushNotificationService,
    PushNotificationServiceHub,
} from './push-notification.service'

const fcmUrl = 'https://fcm.googleapis.com/v1/projects/test-project/messages:send'

const createSendPushNotificationInvocation = (token: string | null | undefined): CyclotronJobInvocationHogFunction => {
    const hogFunction = createHogFunction({
        name: 'Test FCM function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
        inputs_schema: [
            {
                type: 'push_subscription',
                platform: 'android',
                key: 'device_token',
                label: 'Device Token',
            },
        ],
    })

    const invocation = createExampleInvocation(hogFunction, {
        inputs: token !== undefined ? { device_token: token } : {},
    })

    invocation.queueParameters = {
        type: 'sendPushNotification',
        url: fcmUrl,
        method: 'POST',
    } as any

    invocation.state.vmState = { stack: [] } as any

    return invocation
}

describe('PushNotificationService', () => {
    let service: PushNotificationService
    let hub: PushNotificationServiceHub
    let hogInputsService: HogInputsService
    let pushSubscriptionsManager: PushSubscriptionsManagerService
    let fetchUtils: PushNotificationFetchUtils

    const mockTrackedFetch = jest.fn()
    const mockIsFetchResponseRetriable = jest.fn()

    beforeEach(() => {
        hub = {
            CDP_FETCH_RETRIES: 3,
            CDP_FETCH_BACKOFF_BASE_MS: 1000,
            CDP_FETCH_BACKOFF_MAX_MS: 10000,
        }
        hogInputsService = {
            loadIntegrationInputs: jest.fn().mockResolvedValue({}),
        } as any
        pushSubscriptionsManager = {
            updateLastSuccessfullyUsedAtByToken: jest.fn().mockResolvedValue(undefined),
            deactivateByTokens: jest.fn().mockResolvedValue(undefined),
            updateTokenLifecycle: jest.fn().mockResolvedValue(undefined),
        } as any

        fetchUtils = {
            trackedFetch: mockTrackedFetch,
            isFetchResponseRetriable: mockIsFetchResponseRetriable,
            maxFetchTimeoutMs: 10000,
        }

        service = new PushNotificationService(hub, hogInputsService, pushSubscriptionsManager, fetchUtils)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('executeSendPushNotification', () => {
        it('throws when queue parameters type is not sendPushNotification', async () => {
            const invocation = createSendPushNotificationInvocation('token')
            invocation.queueParameters = { type: 'fetch', url: fcmUrl, method: 'POST' } as any

            await expect(service.executeSendPushNotification(invocation)).rejects.toThrow('Bad invocation')
            expect(mockTrackedFetch).not.toHaveBeenCalled()
        })

        it('calls trackedFetch with url and fetchParams', async () => {
            const invocation = createSendPushNotificationInvocation('token')
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 200,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(mockTrackedFetch).toHaveBeenCalledWith({
                url: fcmUrl,
                fetchParams: expect.objectContaining({ method: 'POST' }),
                templateId: 'unknown',
            })
        })

        it('returns result with execResult and metric sendPushNotification on success', async () => {
            const invocation = createSendPushNotificationInvocation('token')
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 200,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.execResult).toEqual({ status: 200, body: {} })
            expect(result.metrics).toContainEqual(
                expect.objectContaining({
                    metric_name: 'sendPushNotification',
                    count: 1,
                })
            )
            expect(result.finished).toBe(false)
        })

        it('logs warning when token is not found in inputs', async () => {
            const invocation = createSendPushNotificationInvocation(null)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 200,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs.map((log) => log.message)).toContain(
                'FCM token not found in inputs, skipping FCM response handling'
            )
            expect(pushSubscriptionsManager.updateTokenLifecycle).not.toHaveBeenCalled()
        })

        it('handles successful response (200) and calls updateTokenLifecycle', async () => {
            const token = 'test-fcm-token-123'
            const invocation = createSendPushNotificationInvocation(token)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 200,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(pushSubscriptionsManager.updateTokenLifecycle).toHaveBeenCalledWith(1, token, 200, undefined)
        })

        it('handles 404 response and calls updateTokenLifecycle (deactivate)', async () => {
            const token = 'test-fcm-token-123'
            const invocation = createSendPushNotificationInvocation(token)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 404,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(pushSubscriptionsManager.updateTokenLifecycle).toHaveBeenCalledWith(1, token, 404, undefined)
        })

        it('handles 400 with INVALID_ARGUMENT and passes error details to updateTokenLifecycle', async () => {
            const token = 'test-fcm-token-123'
            const responseBody = {
                error: {
                    code: 400,
                    details: [
                        {
                            '@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError',
                            errorCode: 'INVALID_ARGUMENT',
                        },
                    ],
                },
            }
            const invocation = createSendPushNotificationInvocation(token)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 400,
                    text: () => Promise.resolve(JSON.stringify(responseBody)),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(pushSubscriptionsManager.updateTokenLifecycle).toHaveBeenCalledWith(
                1,
                token,
                400,
                responseBody.error.details
            )
        })

        it('handles 400 with empty error details and calls updateTokenLifecycle', async () => {
            const token = 'test-fcm-token-123'
            const responseBody = {
                error: {
                    code: 400,
                    details: [],
                },
            }
            const invocation = createSendPushNotificationInvocation(token)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 400,
                    text: () => Promise.resolve(JSON.stringify(responseBody)),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(pushSubscriptionsManager.updateTokenLifecycle).toHaveBeenCalledWith(1, token, 400, [])
        })

        it('handles other status codes and still calls updateTokenLifecycle', async () => {
            const token = 'test-fcm-token-123'
            const invocation = createSendPushNotificationInvocation(token)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 500,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(pushSubscriptionsManager.updateTokenLifecycle).toHaveBeenCalledWith(1, token, 500, undefined)
        })

        it('schedules retry when response is retriable', async () => {
            const token = 'test-fcm-token-123'
            const invocation = createSendPushNotificationInvocation(token)
            mockIsFetchResponseRetriable.mockReturnValue(true)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 500,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.invocation.queue).toBe('hog')
            expect(result.invocation.queueParameters?.type).toBe('sendPushNotification')
            expect(result.invocation.queueScheduledAt).toBeDefined()
            expect(result.error).toBeUndefined()
        })

        it('sets result.error when retries exhausted and not retriable', async () => {
            const token = 'test-fcm-token-123'
            const invocation = createSendPushNotificationInvocation(token)
            mockIsFetchResponseRetriable.mockReturnValue(false)
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 500,
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.error).toBeInstanceOf(Error)
            expect(result.error?.message).toContain('status code 500')
        })
    })
})
