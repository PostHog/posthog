import { generateKeyPairSync } from 'crypto'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleInvocation, createHogFunction } from '~/cdp/_tests/fixtures'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { parseJSON } from '~/common/utils/json-parse'

import { IntegrationManagerService } from '../managers/integration-manager.service'
import { MessageAssetsService } from './message-assets.service'
import { PushNotificationFetchUtils, PushNotificationService } from './push-notification.service'

const encryptedFields = new EncryptedFields('01234567890123456789012345678901')

const testEcKey = generateKeyPairSync('ec', {
    namedCurve: 'prime256v1',
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    publicKeyEncoding: { type: 'spki', format: 'pem' },
}).privateKey

const createSendPushNotificationInvocation = (
    personProperties?: Record<string, any>
): CyclotronJobInvocationHogFunction => {
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

    const invocation = createExampleInvocation(hogFunction)

    invocation.queueParameters = {
        type: 'sendPushNotification',
        integrationIds: [1],
        distinctId: 'test-distinct-id',
        payload: {
            title: 'Test notification',
            body: 'Hello from PostHog',
        },
    } as any

    invocation.state.vmState = { stack: [] } as any

    if (personProperties) {
        invocation.state.globals.person = {
            ...(invocation.state.globals.person ?? { id: 'person-1', name: 'Test', url: '' }),
            properties: personProperties,
        }
    }

    return invocation
}

describe('PushNotificationService', () => {
    let service: PushNotificationService
    let integrationManager: IntegrationManagerService
    let fetchUtils: PushNotificationFetchUtils
    let valkeyStore: Map<string, string>
    let mockValkeySet: jest.Mock
    let mockValkey: any

    const mockTrackedFetch = jest.fn()

    const firebaseIntegration = {
        id: 1,
        team_id: 1,
        kind: 'firebase' as const,
        config: { project_id: 'test-project' },
        sensitive_config: { access_token: 'test-access-token' },
    }

    beforeEach(() => {
        integrationManager = {
            get: jest.fn().mockResolvedValue(firebaseIntegration),
        } as any

        fetchUtils = {
            trackedFetch: mockTrackedFetch,
            maxFetchTimeoutMs: 10000,
            maxRetries: 3,
            backoffBaseMs: 1000,
            backoffMaxMs: 30000,
        }

        valkeyStore = new Map<string, string>()
        mockValkeySet = jest.fn((key: string, value: string) => {
            valkeyStore.set(key, value)
            return 'OK'
        })
        mockValkey = {
            useClient: jest.fn((_opts: any, fn: any) =>
                fn({
                    get: (key: string) => valkeyStore.get(key) ?? null,
                    set: mockValkeySet,
                })
            ),
        } as any

        service = new PushNotificationService(integrationManager, encryptedFields, fetchUtils, mockValkey)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('executeSendPushNotification', () => {
        it('throws when queue parameters type is not sendPushNotification', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            invocation.queueParameters = { type: 'fetch', url: 'http://example.com', method: 'POST' } as any

            await expect(service.executeSendPushNotification(invocation)).rejects.toThrow('Bad invocation')
            expect(mockTrackedFetch).not.toHaveBeenCalled()
        })

        it('calls trackedFetch with url and fetchParams', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
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
                url: 'https://fcm.googleapis.com/v1/projects/test-project/messages:send',
                fetchParams: expect.objectContaining({ method: 'POST' }),
                templateId: 'unknown',
            })
        })

        it('returns result with metric push_sent on success', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
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

            expect(result.metrics).toContainEqual(
                expect.objectContaining({
                    metric_kind: 'push',
                    metric_name: 'push_sent',
                    count: 1,
                })
            )
            expect(result.finished).toBe(true)
        })

        it('logs warning and records push_skipped when no device token found', async () => {
            const invocation = createSendPushNotificationInvocation({})

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs.map((log) => log.message)).toContainEqual(
                expect.stringContaining('No active FCM device token found')
            )
            // No token means nothing was delivered — record push_skipped, not push_sent.
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_skipped', count: 1 }))
            expect(result.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_sent' }))
        })

        it('stamps workflow, action and invocation ids into the data payload so opens can be attributed', async () => {
            // An open is captured on the device, so these ids riding along in the payload are the only
            // way the resulting event can be tied back to the workflow and step that sent it.
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            invocation.state.actionId = 'push-step'
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

            const body = parseJSON(mockTrackedFetch.mock.calls[0][0].fetchParams.body)
            // Nested under the single `posthog` key, JSON-encoded: that is the only entry the SDKs read,
            // and FCM's `data` map only accepts string values. Sibling keys would be silently ignored.
            expect(parseJSON(body.message.data.posthog)).toEqual({
                workflow_id: invocation.functionId,
                action_id: 'push-step',
                invocation_id: invocation.id,
            })
        })

        it('carries the batch run id so a batch push open divides against its sends', async () => {
            // A batch run attributes its send metrics to the batch job, not the workflow
            // (`parentRunId ?? functionId`). Without the same id on the open, sends would be counted
            // against the batch and opens against the workflow, and the open rate wouldn't divide.
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            invocation.state.actionId = 'push-step'
            invocation.parentRunId = 'batch-job-1'
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

            const body = parseJSON(mockTrackedFetch.mock.calls[0][0].fetchParams.body)
            expect(parseJSON(body.message.data.posthog)).toEqual({
                workflow_id: invocation.functionId,
                action_id: 'push-step',
                invocation_id: invocation.id,
                parent_run_id: 'batch-job-1',
            })
            // The same id the send metric is filed under, so the two are comparable.
            expect(result.metrics).toContainEqual(
                expect.objectContaining({ metric_name: 'push_sent', app_source_id: 'batch-job-1' })
            )
        })

        it('does not let a custom data key shadow the correlation payload', async () => {
            // `data` is customer-controlled. If a custom key could win, opens would be attributed to
            // whatever workflow the sender named, so the reserved key has to be applied last.
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            ;(invocation.queueParameters as any).payload.data = { posthog: 'not-the-real-workflow' }
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

            const body = parseJSON(mockTrackedFetch.mock.calls[0][0].fetchParams.body)
            expect(parseJSON(body.message.data.posthog).workflow_id).toBe(invocation.functionId)
        })

        describe('message asset capture', () => {
            let serviceWithAssets: PushNotificationService

            const respondWith = (status: number): void => {
                mockTrackedFetch.mockResolvedValue({
                    fetchError: null,
                    fetchResponse: {
                        status,
                        headers: {},
                        text: () => Promise.resolve('{}'),
                        dump: () => Promise.resolve(),
                    },
                    fetchDuration: 10,
                })
            }

            beforeEach(() => {
                serviceWithAssets = new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    mockValkey,
                    new MessageAssetsService({ produce: jest.fn() } as any)
                )
            })

            // Guards the wiring between the send and the Assets tab, which the `buildRowForPush` unit
            // tests can't see: drop the assets service from the constructor call in cdp-services.ts, or
            // narrow the capture condition, and a delivered push stops producing a row while every
            // other test here stays green.
            it.each([
                {
                    outcome: 'was delivered',
                    status: 200,
                    tokens: { '$device_push_subscription_test-project': 'device-token-123' },
                    captured: 'sent',
                },
                { outcome: 'reached no device', status: 200, tokens: {}, captured: 'nothing' },
                {
                    outcome: 'failed terminally',
                    status: 400,
                    tokens: { '$device_push_subscription_test-project': 'device-token-123' },
                    captured: 'nothing',
                },
            ])('captures a push that $outcome as $captured', async ({ status, tokens, captured }) => {
                respondWith(status)
                const invocation = createSendPushNotificationInvocation(
                    Object.fromEntries(
                        Object.entries(tokens).map(([key, token]) => [key, encryptedFields.encrypt(token)])
                    )
                )
                invocation.state.actionId = 'action_push_1'

                const result = await serviceWithAssets.executeSendPushNotification(invocation)

                if (captured === 'nothing') {
                    // An asset is a snapshot of what a recipient received; a send that reached nobody
                    // has none, and email behaves the same way (it captures only on success).
                    expect(result.messageAssets).toEqual([])
                    return
                }
                expect(result.messageAssets).toHaveLength(1)
                expect(result.messageAssets[0]).toMatchObject({
                    kind: 'push',
                    status: captured,
                    action_id: 'action_push_1',
                    subject: 'Test notification',
                })
            })

            it('keeps a delivered notification successful when the capture itself throws', async () => {
                // The send has already gone out at this point, so letting a capture failure surface
                // would fail the invocation and the retry would deliver the notification again.
                respondWith(200)
                const invocation = createSendPushNotificationInvocation({
                    '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
                })
                invocation.state.actionId = 'action_push_1'
                const exploding = new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    mockValkey,
                    {
                        buildRowForPush: () => {
                            throw new Error('boom')
                        },
                    } as any
                )

                const result = await exploding.executeSendPushNotification(invocation)

                expect(result.error).toBeUndefined()
                expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_sent' }))
                expect(result.messageAssets).toEqual([])
                expect(result.logs.map((log) => log.message)).toContainEqual(
                    expect.stringContaining('could not be captured')
                )
            })

            it('records neither a metric nor an asset for a test send', async () => {
                // "Run test" really delivers, but it must not show up as a workflow send: email
                // already skips both, and a test row on the Assets tab reads as a real delivery.
                respondWith(200)
                const invocation = createSendPushNotificationInvocation({
                    '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
                })
                invocation.state.actionId = 'action_push_1'

                const result = await serviceWithAssets.executeSendPushNotification(invocation, true)

                expect(result.error).toBeUndefined()
                expect(result.metrics).toEqual([])
                expect(result.messageAssets).toEqual([])
                expect(result.logs.map((log) => log.message)).toContainEqual(expect.stringContaining('accepted by FCM'))
            })

            it('captures one asset per notification, not one per delivered channel', async () => {
                respondWith(200)
                integrationManager.get = jest
                    .fn()
                    .mockResolvedValue({ ...firebaseIntegration, kind: 'firebase' as const })
                const invocation = createSendPushNotificationInvocation({
                    '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
                })
                invocation.state.actionId = 'action_push_1'
                ;(invocation.queueParameters as any).integrationIds = [1, 2]

                const result = await serviceWithAssets.executeSendPushNotification(invocation)

                expect(result.messageAssets).toHaveLength(1)
            })
        })

        it('does not match tokens for a different app identifier', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_other-project': encryptedFields.encrypt('other-token'),
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs.map((log) => log.message)).toContainEqual(
                expect.stringContaining('No active FCM device token found')
            )
            expect(mockTrackedFetch).not.toHaveBeenCalled()
        })

        it('fails terminally (no retry) on a non-retriable 4xx', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            // A 400 is a client error that won't change on retry (bad payload), unlike a 429/5xx.
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 400,
                    headers: {},
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.error).toBeTruthy()
            expect(result.finished).toBe(true)
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
        })

        it('reschedules a transient failure and re-runs the send on the retry (round trip)', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            // First attempt: FCM 500 is transient, so the invocation is rescheduled rather than dropped.
            mockTrackedFetch.mockResolvedValueOnce({
                fetchError: null,
                fetchResponse: {
                    status: 500,
                    headers: {},
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const first = await service.executeSendPushNotification(invocation)

            expect(first.finished).toBe(false)
            expect(first.invocation.queueScheduledAt).toBeDefined()
            expect(first.error).toBeUndefined()
            // The P1 guard: queueParameters must be restored, or the retry dequeue resumes the hog VM
            // instead of re-entering this service, pops an empty stack, and drops the notification.
            expect(first.invocation.queueParameters?.type).toBe('sendPushNotification')
            expect(first.invocation.queueMetadata).toEqual(expect.objectContaining({ tries: 1 }))
            // A rescheduled attempt reports no terminal outcome yet.
            expect(first.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))

            // Feed the rescheduled invocation back through the executor: the send must actually re-run.
            mockTrackedFetch.mockResolvedValueOnce({
                fetchError: null,
                fetchResponse: {
                    status: 200,
                    headers: {},
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const second = await service.executeSendPushNotification(first.invocation)

            expect(second.finished).toBe(true)
            expect(second.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_sent', count: 1 }))
        })

        it('stops rescheduling once the retry budget is exhausted', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            invocation.queueMetadata = { tries: 3 } // == maxRetries
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 429,
                    headers: {},
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeTruthy()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
        })

        it('prunes an unregistered FCM token and skips the channel without erroring', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
            })
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 404,
                    text: () =>
                        Promise.resolve(
                            JSON.stringify({ error: { status: 'NOT_FOUND', details: [{ errorCode: 'UNREGISTERED' }] } })
                        ),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            // Dead token: removed via a $unset person update, and the channel is skipped (not errored → no retry).
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toContainEqual(
                expect.objectContaining({
                    event: '$set',
                    distinct_id: 'test-distinct-id',
                    properties: { $unset: ['$device_push_subscription_test-project'] },
                })
            )
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_skipped' }))
        })

        it('puts an iOS subtitle in the APNS alert, not the FCM notification (FCM rejects notification.subtitle)', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
            })
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: { title: 'T', body: 'B', apns: { subtitle: 'Sub' } },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            const body = parseJSON(mockTrackedFetch.mock.calls[0][0].fetchParams.body)
            expect(body.message.notification.subtitle).toBeUndefined()
            expect(body.message.apns.payload.aps.alert).toEqual({ title: 'T', body: 'B', subtitle: 'Sub' })
        })

        it('returns error when integration not found', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
            ;(integrationManager.get as jest.Mock).mockResolvedValue(undefined)

            const result = await service.executeSendPushNotification(invocation)

            expect(result.error).toBeTruthy()
            expect(result.logs.map((log) => log.message)).toContain('Push notification integration not found')
        })

        it('handles missing person properties gracefully', async () => {
            const invocation = createSendPushNotificationInvocation()

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs.map((log) => log.message)).toContainEqual(
                expect.stringContaining('No active FCM device token found')
            )
        })
    })

    describe('APNS path', () => {
        const apnsIntegration = {
            id: 2,
            team_id: 1,
            kind: 'apns' as const,
            config: { key_id: 'KEY123', team_id: 'TEAM456', bundle_id: 'com.example.app' },
            sensitive_config: { signing_key: testEcKey },
        }

        beforeEach(() => {
            ;(integrationManager.get as jest.Mock).mockResolvedValue(apnsIntegration)
        })

        it('sends push notification via APNS', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 200,
                    text: () => Promise.resolve(''),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 15,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.finished).toBe(true)
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_sent', count: 1 }))
            expect(mockTrackedFetch).toHaveBeenCalledWith({
                url: 'https://api.push.apple.com/3/device/apns-device-token',
                fetchParams: expect.objectContaining({
                    method: 'POST',
                    allowH2: true,
                    headers: expect.objectContaining({
                        'apns-topic': 'com.example.app',
                        'apns-push-type': 'alert',
                    }),
                }),
                templateId: 'unknown',
            })
        })

        it('reuses a cached APNS provider token across sends instead of minting one each time', async () => {
            const send = (): Promise<any> =>
                service.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                    })
                )
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 15,
            })

            await send()
            await send()

            // The JWT is written to Valkey once and read back on the second send. Minting a new token per
            // send is what makes Apple return 429 TooManyProviderTokenUpdates.
            expect(mockValkeySet).toHaveBeenCalledTimes(1)
            // Apple accepts a provider token for up to an hour, so the TTL has to stay under that.
            expect(mockValkeySet).toHaveBeenCalledWith(
                expect.stringContaining('@posthog/apns-provider-jwt/'),
                expect.any(String),
                'EX',
                2700
            )
        })

        it('reuses the pod-local APNS token when Valkey is unavailable', async () => {
            // Both Valkey calls are failOpen, so an outage makes the read return null. Without the
            // pod-local fallback every send mints a token and Apple answers 429 TooManyProviderTokenUpdates.
            const failingValkey = {
                useClient: jest.fn().mockResolvedValue(null),
            } as any
            const offlineService = new PushNotificationService(
                integrationManager,
                encryptedFields,
                fetchUtils,
                failingValkey
            )
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 15,
            })
            const send = (): Promise<any> =>
                offlineService.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                    })
                )

            mockTrackedFetch.mockClear()
            await send()
            await send()

            const authHeaders = mockTrackedFetch.mock.calls.map(
                (call: any) => call[0].fetchParams.headers.Authorization
            )
            expect(authHeaders).toHaveLength(2)
            expect(authHeaders[0]).toEqual(expect.stringContaining('bearer '))
            expect(authHeaders[0]).toBe(authHeaders[1])
        })

        it('sets apns-priority to 5 for passive interruption level', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: {
                    title: 'Test',
                    apns: { interruptionLevel: 'passive' },
                },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(mockTrackedFetch).toHaveBeenCalledWith(
                expect.objectContaining({
                    fetchParams: expect.objectContaining({
                        headers: expect.objectContaining({ 'apns-priority': '5' }),
                    }),
                })
            )
        })

        it('sets apns-priority to 10 for active interruption level', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: {
                    title: 'Test',
                    apns: { interruptionLevel: 'active' },
                },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(mockTrackedFetch).toHaveBeenCalledWith(
                expect.objectContaining({
                    fetchParams: expect.objectContaining({
                        headers: expect.objectContaining({ 'apns-priority': '10' }),
                    }),
                })
            )
        })

        it('includes apns-collapse-id and apns-expiration headers when set', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: {
                    title: 'Test',
                    collapseKey: 'my-collapse',
                    ttlSeconds: 3600,
                },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            expect(mockTrackedFetch).toHaveBeenCalledWith(
                expect.objectContaining({
                    fetchParams: expect.objectContaining({
                        headers: expect.objectContaining({
                            'apns-collapse-id': 'my-collapse',
                            'apns-expiration': expect.stringMatching(/^\d+$/),
                        }),
                    }),
                })
            )
        })

        it('logs warning when no APNS device token found', async () => {
            const invocation = createSendPushNotificationInvocation({})

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs.map((log) => log.message)).toContainEqual(
                expect.stringContaining('No active APNS device token found')
            )
            expect(mockTrackedFetch).not.toHaveBeenCalled()
        })

        it('throws when APNS integration is missing required fields', async () => {
            ;(integrationManager.get as jest.Mock).mockResolvedValue({
                ...apnsIntegration,
                config: { key_id: 'KEY123' },
            })
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.error).toBeTruthy()
            expect(result.error).toContain('missing required fields')
        })

        it('generates a valid ES256 JWT with ieee-p1363 signature', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            const authHeader = mockTrackedFetch.mock.calls[0][0].fetchParams.headers['Authorization']
            const jwt = authHeader.replace('bearer ', '')
            const [headerB64, claimsB64, signatureB64] = jwt.split('.')

            const header = parseJSON(Buffer.from(headerB64, 'base64url').toString())
            expect(header).toEqual({ alg: 'ES256', kid: 'KEY123' })

            const claims = parseJSON(Buffer.from(claimsB64, 'base64url').toString())
            expect(claims.iss).toBe('TEAM456')
            expect(claims.iat).toBeGreaterThan(0)

            // IEEE P1363 ES256 signatures are exactly 64 bytes (32 bytes r + 32 bytes s)
            const signatureBytes = Buffer.from(signatureB64, 'base64url')
            expect(signatureBytes.length).toBe(64)
        })

        it('sets error when APNS returns failure', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 403,
                    text: () => Promise.resolve(JSON.stringify({ reason: 'InvalidProviderToken' })),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.error).toBeTruthy()
            expect(result.error).toContain('InvalidProviderToken')
        })

        it('does not let custom data overwrite the reserved aps payload', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            // A custom data key named `aps` must not clobber the real notification payload.
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: { title: 'Real title', data: { aps: 'hijacked', custom: 'kept' } },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 15,
            })

            await service.executeSendPushNotification(invocation)

            const body = parseJSON(mockTrackedFetch.mock.calls[0][0].fetchParams.body)
            expect(body.aps.alert.title).toBe('Real title')
            expect(body.custom).toBe('kept')
        })

        it('prunes an unregistered APNS token (410) and skips the channel', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-token'),
            })
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 410,
                    text: () => Promise.resolve(JSON.stringify({ reason: 'Unregistered' })),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toContainEqual(
                expect.objectContaining({
                    event: '$set',
                    properties: { $unset: ['$device_push_subscription_com.example.app'] },
                })
            )
        })
    })

    describe('multiple channels', () => {
        const apnsIntegration = {
            id: 2,
            team_id: 1,
            kind: 'apns' as const,
            config: { key_id: 'KEY123', team_id: 'TEAM456', bundle_id: 'com.example.app' },
            sensitive_config: { signing_key: testEcKey },
        }
        const ok200 = {
            fetchError: null,
            fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
            fetchDuration: 10,
        }

        it('delivers to every channel in the list, not just the first', async () => {
            ;(integrationManager.get as jest.Mock).mockImplementation((id: number) =>
                Promise.resolve(id === 1 ? firebaseIntegration : apnsIntegration)
            )
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-token'),
            })
            invocation.queueParameters = { ...invocation.queueParameters, integrationIds: [1, 2] } as any
            mockTrackedFetch.mockResolvedValue(ok200)

            await service.executeSendPushNotification(invocation)

            // The bug: a per-channel loop in hog only ran once, so only the first channel delivered.
            expect(mockTrackedFetch).toHaveBeenCalledTimes(2)
            const urls = mockTrackedFetch.mock.calls.map((c: any) => c[0].url)
            expect(urls.some((u: string) => u.includes('fcm.googleapis.com'))).toBe(true)
            expect(urls.some((u: string) => u.includes('push.apple.com'))).toBe(true)
        })

        it('deduplicates repeated channel ids so a device is not notified twice', async () => {
            ;(integrationManager.get as jest.Mock).mockResolvedValue(firebaseIntegration)
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
            })
            invocation.queueParameters = { ...invocation.queueParameters, integrationIds: [1, 1, 1] } as any
            mockTrackedFetch.mockResolvedValue(ok200)

            await service.executeSendPushNotification(invocation)

            // Three duplicate ids resolve to one unique channel — deliver once, not three times.
            expect(mockTrackedFetch).toHaveBeenCalledTimes(1)
        })

        it('keeps delivering to healthy channels when one channel errors', async () => {
            const brokenApns = { ...apnsIntegration, config: {}, sensitive_config: {} }
            ;(integrationManager.get as jest.Mock).mockImplementation((id: number) =>
                Promise.resolve(id === 1 ? firebaseIntegration : brokenApns)
            )
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
            })
            invocation.queueParameters = { ...invocation.queueParameters, integrationIds: [1, 2] } as any
            mockTrackedFetch.mockResolvedValue(ok200)

            const result = await service.executeSendPushNotification(invocation)

            // FCM still delivers though the APNS channel throws; a partial success is not a hard error.
            expect(mockTrackedFetch).toHaveBeenCalledTimes(1)
            expect(mockTrackedFetch.mock.calls[0][0].url).toContain('fcm.googleapis.com')
            expect(result.error).toBeUndefined()
        })

        it('reschedules without re-counting the skipped channel on the retry attempt', async () => {
            ;(integrationManager.get as jest.Mock).mockImplementation((id: number) =>
                Promise.resolve(id === 1 ? firebaseIntegration : apnsIntegration)
            )
            // FCM has no token (skipped), APNS fails transiently. Nothing delivered, so this reschedules,
            // and the skip must not be counted on the rescheduled attempt — it's emitted only at the
            // terminal outcome, so per-notification counts don't inflate on every retry.
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-token'),
            })
            invocation.queueParameters = { ...invocation.queueParameters, integrationIds: [1, 2] } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: {
                    status: 500,
                    headers: {},
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.finished).toBe(false)
            expect(result.invocation.queueParameters?.type).toBe('sendPushNotification')
            expect(result.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_skipped' }))
            expect(result.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
        })

        it('reschedules using the longest Retry-After across failed channels', async () => {
            ;(integrationManager.get as jest.Mock).mockImplementation((id: number) =>
                Promise.resolve(id === 1 ? firebaseIntegration : apnsIntegration)
            )
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-token'),
            })
            invocation.queueParameters = { ...invocation.queueParameters, integrationIds: [1, 2] } as any
            // FCM 500 (short backoff) then APNs 429 with Retry-After: 30. Retrying re-attempts both, so the
            // delay must clear the longer 30s window, not FCM's sub-2s backoff.
            mockTrackedFetch.mockResolvedValueOnce({
                fetchError: null,
                fetchResponse: {
                    status: 500,
                    headers: {},
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })
            mockTrackedFetch.mockResolvedValueOnce({
                fetchError: null,
                fetchResponse: {
                    status: 429,
                    headers: { 'retry-after': '30' },
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.finished).toBe(false)
            const delayMs = result.invocation.queueScheduledAt!.toMillis() - Date.now()
            expect(delayMs).toBeGreaterThan(20_000)
            expect(delayMs).toBeLessThanOrEqual(30_000)
        })
    })
})
