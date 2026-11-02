import { createHash, generateKeyPairSync } from 'crypto'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleInvocation, createHogFunction } from '~/cdp/_tests/fixtures'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { deviceSubscriptionKey } from '~/cdp/utils/push-subscription-utils'
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
    // The step's Distinct ID input names the run's own person, the template default.
    invocation.state.globals.event.distinct_id = 'test-distinct-id'

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
    let personsManager: { getCyclotronPerson: jest.Mock }

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
        mockValkeySet = jest.fn((key: string, value: string, ...args: (string | number)[]) => {
            if (args.includes('NX') && valkeyStore.has(key)) {
                return null
            }
            valkeyStore.set(key, value)
            return 'OK'
        })
        mockValkey = {
            useClient: jest.fn((_opts: any, fn: any) =>
                fn({
                    get: (key: string) => valkeyStore.get(key) ?? null,
                    set: mockValkeySet,
                    eval: (_script: string, _keys: number, key: string, rejected: string) => {
                        const current = valkeyStore.get(key) ?? null
                        if (current === rejected) {
                            valkeyStore.delete(key)
                            return null
                        }
                        return current
                    },
                })
            ),
        } as any

        personsManager = { getCyclotronPerson: jest.fn().mockResolvedValue(null) }

        service = new PushNotificationService(
            integrationManager,
            encryptedFields,
            fetchUtils,
            mockValkey,
            personsManager as any
        )
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
                teamId: invocation.teamId,
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
            expect(result.deliveredToRecipient).toBe(true)
        })

        it('logs warning and records push_skipped when no device token found', async () => {
            const invocation = createSendPushNotificationInvocation({})

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs).toContainEqual(
                expect.objectContaining({
                    level: 'warn',
                    message: expect.stringContaining('No active FCM device token found'),
                })
            )
            // No token means nothing was delivered — record push_skipped, not push_sent.
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_skipped', count: 1 }))
            expect(result.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_sent' }))
            // Billing reads this, so a regression here charges for a notification nobody received.
            expect(result.deliveredToRecipient).toBe(false)
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
                    personsManager as any,
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
                    delivery: undefined as string | undefined,
                },
                { outcome: 'reached no device', status: 200, tokens: {}, captured: 'nothing' },
                {
                    outcome: 'was silent',
                    status: 200,
                    tokens: { '$device_push_subscription_test-project': 'device-token-123' },
                    captured: 'nothing',
                    delivery: 'silent',
                },
                {
                    outcome: 'failed terminally',
                    status: 400,
                    tokens: { '$device_push_subscription_test-project': 'device-token-123' },
                    captured: 'nothing',
                },
            ])('captures a push that $outcome as $captured', async ({ status, tokens, captured, delivery }) => {
                respondWith(status)
                const invocation = createSendPushNotificationInvocation(
                    Object.fromEntries(
                        Object.entries(tokens).map(([key, token]) => [key, encryptedFields.encrypt(token)])
                    )
                )
                invocation.state.actionId = 'action_push_1'
                if (delivery) {
                    ;(invocation.queueParameters as any).payload = { delivery, data: { k: 'v' } }
                }

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
                    personsManager as any,
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

        it.each([false, true])(
            'fails terminally (no retry) on a non-retriable 4xx, protected: %s',
            async (sensitive) => {
                const invocation = createSendPushNotificationInvocation({
                    '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
                })
                invocation.hogFunction.metadata = { ...invocation.hogFunction.metadata, sensitive }
                // A 400 is a client error that won't change on retry (bad payload), unlike a 429/5xx.
                // FCM can quote the rejected message back in the error.
                mockTrackedFetch.mockResolvedValue({
                    fetchError: null,
                    fetchResponse: {
                        status: 400,
                        headers: {},
                        text: () => Promise.resolve('{"error":{"message":"Invalid value: Your code is 482913"}}'),
                        dump: () => Promise.resolve(),
                    },
                    fetchDuration: 10,
                })

                const result = await service.executeSendPushNotification(invocation)

                expect(result.error).toBeTruthy()
                expect(result.finished).toBe(true)
                expect(result.invocation.queueScheduledAt).toBeUndefined()
                expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
                expect(JSON.stringify(result.logs).includes('482913')).toBe(!sensitive)
            }
        )

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

        it.each([
            {
                delivery: 'android_data_only',
                notification: undefined,
                aps: { alert: { title: 'T', body: 'B' }, 'mutable-content': 1 },
                apnsHeaders: undefined,
            },
            {
                delivery: 'silent',
                notification: undefined,
                aps: { 'content-available': 1 },
                apnsHeaders: { 'apns-push-type': 'background', 'apns-priority': '5' },
            },
            {
                delivery: undefined,
                notification: { title: 'T', body: 'B', image: 'https://example.com/i.png' },
                aps: undefined,
                apnsHeaders: undefined,
            },
        ])('builds the FCM message for delivery $delivery', async ({ delivery, notification, aps, apnsHeaders }) => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
            })
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: {
                    delivery,
                    title: 'T',
                    body: 'B',
                    image: 'https://example.com/i.png',
                    data: { chat_id: 'c1' },
                    android: { priority: 'high', tag: 'chat-c1' },
                },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            await service.executeSendPushNotification(invocation)

            const { message } = parseJSON(mockTrackedFetch.mock.calls[0][0].fetchParams.body)
            expect(message.notification).toEqual(notification)
            // Android draws a notification from `android.notification` too, so data-only must drop it.
            expect(message.android).toEqual(
                delivery ? { priority: 'HIGH' } : { priority: 'HIGH', notification: { tag: 'chat-c1' } }
            )
            expect(message.data.chat_id).toBe('c1')
            expect(message.apns?.payload.aps).toEqual(aps)
            expect(message.apns?.headers).toEqual(apnsHeaders)
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

    describe('recipient named by the step', () => {
        // The run's person is whoever the trigger ran for; the step's Distinct ID input can name
        // someone else (a manual run's person is the clicker, not the app user being tested).
        const runPersonKey = deviceSubscriptionKey('test-project', 'run-person-token')
        const namedPersonKey = deviceSubscriptionKey('test-project', 'named-person-token')

        const namedPerson = (properties: Record<string, any>) => ({
            id: 'named-person-id',
            name: 'Named',
            url: '',
            distinct_id: 'named-user',
            properties,
        })

        const invocationNaming = (distinctId: string): CyclotronJobInvocationHogFunction => {
            const invocation = createSendPushNotificationInvocation({
                [runPersonKey]: encryptedFields.encrypt('run-person-token'),
            })
            ;(invocation.queueParameters as any).distinctId = distinctId
            invocation.hogFunction.template_id = 'template-native-push'
            invocation.state.actionId = 'push'
            return invocation
        }

        const sentTokens = (): string[] =>
            mockTrackedFetch.mock.calls.map((call: any) => parseJSON(call[0].fetchParams.body).message.token)

        const ok = () => ({
            fetchError: null,
            fetchResponse: { status: 200, text: () => Promise.resolve('{}'), dump: () => Promise.resolve() },
            fetchDuration: 10,
        })

        const unregistered = () => ({
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

        it('sends to the devices of the person the input names, not the run person', async () => {
            personsManager.getCyclotronPerson.mockResolvedValue(
                namedPerson({ [namedPersonKey]: encryptedFields.encrypt('named-person-token') })
            )
            mockTrackedFetch.mockResolvedValue(ok())

            // Trailing whitespace from the editor must not turn a valid id into an unknown person.
            const result = await service.executeSendPushNotification(invocationNaming('named-user  '))

            expect(personsManager.getCyclotronPerson).toHaveBeenCalledWith(1, 'named-user', 'distinct_id', {
                forceFresh: true,
            })
            expect(sentTokens()).toEqual(['named-person-token'])
            expect(result.deliveredToRecipient).toBe(true)
        })

        it.each([
            ['test-distinct-id', 'test-distinct-id'],
            ['  test-distinct-id ', 'test-distinct-id'],
            ['', 'test-distinct-id'],
            [' user-42 ', ' user-42 '],
        ])(
            'reads the run person without a lookup when the input is %j and the run distinct_id is %j',
            async (distinctId, runDistinctId) => {
                mockTrackedFetch.mockResolvedValue(ok())
                const invocation = invocationNaming(distinctId)
                invocation.state.globals.event.distinct_id = runDistinctId

                await service.executeSendPushNotification(invocation)

                expect(personsManager.getCyclotronPerson).not.toHaveBeenCalled()
                expect(sentTokens()).toEqual(['run-person-token'])
            }
        )

        it.each([
            [
                'a custom destination',
                (invocation: CyclotronJobInvocationHogFunction) => delete invocation.state.actionId,
            ],
            [
                'a workflow step built on another template',
                (invocation: CyclotronJobInvocationHogFunction) =>
                    (invocation.hogFunction.template_id = 'template-webhook'),
            ],
        ])('keeps %s on the run person when it names someone else', async (_, notAPushStep) => {
            mockTrackedFetch.mockResolvedValue(ok())
            const invocation = invocationNaming('named-user')
            notAPushStep(invocation)

            await service.executeSendPushNotification(invocation)

            expect(personsManager.getCyclotronPerson).not.toHaveBeenCalled()
            expect(sentTokens()).toEqual(['run-person-token'])
        })

        it('skips with a warning naming the input when it matches no person', async () => {
            // Falling back to the run person here would notify someone the step did not name.
            const result = await service.executeSendPushNotification(invocationNaming('nobody'))

            expect(mockTrackedFetch).not.toHaveBeenCalled()
            expect(result.error).toBeUndefined()
            expect(result.logs.map((log) => log.message)).toContainEqual(
                expect.stringContaining('No person found for distinct_id: nobody')
            )
            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_skipped', count: 1 }))
            expect(result.deliveredToRecipient).toBe(false)
        })

        it('names the person it checked in the no-token warning', async () => {
            personsManager.getCyclotronPerson.mockResolvedValue(namedPerson({}))

            const result = await service.executeSendPushNotification(invocationNaming('named-user'))

            expect(mockTrackedFetch).not.toHaveBeenCalled()
            expect(result.logs.map((log) => log.message)).toContainEqual(
                'No active FCM device token found for distinct_id: named-user'
            )
        })

        it('prunes a dead token from the named person and leaves the run snapshot alone', async () => {
            personsManager.getCyclotronPerson.mockResolvedValue(
                namedPerson({ [namedPersonKey]: encryptedFields.encrypt('named-person-token') })
            )
            mockTrackedFetch.mockResolvedValue(unregistered())
            const invocation = invocationNaming('named-user')

            const result = await service.executeSendPushNotification(invocation)

            expect(result.capturedPostHogEvents).toEqual([
                expect.objectContaining({ distinct_id: 'named-user', properties: { $unset: [namedPersonKey] } }),
            ])
            // The snapshot belongs to the run person, whose token is still live.
            expect(result.invocation.state.globals.person?.properties).toHaveProperty(runPersonKey)
        })

        it('reschedules when the person lookup fails, and fails once the retries are spent', async () => {
            personsManager.getCyclotronPerson.mockRejectedValue(new Error('personhog unavailable'))
            const invocation = invocationNaming('named-user')

            const first = await service.executeSendPushNotification(invocation)

            expect(mockTrackedFetch).not.toHaveBeenCalled()
            expect(first.finished).toBe(false)
            expect(first.invocation.queueScheduledAt).toBeDefined()
            expect(first.invocation.queueParameters).toEqual(invocation.queueParameters)
            expect(first.invocation.queueMetadata).toEqual(expect.objectContaining({ tries: 1 }))
            expect(first.metrics).toEqual([])

            invocation.queueMetadata = { tries: 3 } // == maxRetries
            await expect(service.executeSendPushNotification(invocation)).rejects.toThrow('personhog unavailable')
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
                teamId: invocation.teamId,
            })
        })

        it('sends a silent push as a background push with no alert, sound or badge', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
            })
            invocation.queueParameters = {
                ...invocation.queueParameters,
                payload: {
                    delivery: 'silent',
                    data: { challenge_id: 'ch1' },
                    apns: { sound: 'default', badge: 3, interruptionLevel: 'time-sensitive' },
                },
            } as any
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 10,
            })

            const result = await service.executeSendPushNotification(invocation)

            expect(result.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_sent', count: 1 }))
            const { headers, body } = mockTrackedFetch.mock.calls[0][0].fetchParams
            expect(headers).toMatchObject({ 'apns-push-type': 'background', 'apns-priority': '5' })
            const sent = parseJSON(body)
            expect(sent.aps).toEqual({ 'content-available': 1 })
            expect(sent.challenge_id).toBe('ch1')
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
            expect(
                mockValkeySet.mock.calls.filter(([key]: [string]) => key.startsWith('@posthog/apns-provider-jwt/'))
            ).toHaveLength(1)
            // Apple accepts a provider token for up to an hour, so the TTL has to stay under that.
            expect(mockValkeySet).toHaveBeenCalledWith(
                expect.stringContaining('@posthog/apns-provider-jwt/'),
                expect.any(String),
                'EX',
                2700,
                'NX'
            )
        })

        it.each([
            ['concurrent sends on one pod', 1],
            ['concurrent sends across pods sharing Valkey', 3],
        ])('presents one APNS provider token for %s', async (_name, podCount) => {
            const pods = Array.from(
                { length: podCount },
                () =>
                    new PushNotificationService(
                        integrationManager,
                        encryptedFields,
                        fetchUtils,
                        mockValkey,
                        personsManager as any
                    )
            )
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 15,
            })
            mockTrackedFetch.mockClear()

            await Promise.all(
                Array.from({ length: 20 }, (_, i) =>
                    pods[i % podCount].executeSendPushNotification(
                        createSendPushNotificationInvocation({
                            '$device_push_subscription_com.example.app': encryptedFields.encrypt(`apns-device-${i}`),
                        })
                    )
                )
            )

            const authHeaders = new Set(
                mockTrackedFetch.mock.calls.map((call: any) => call[0].fetchParams.headers.Authorization)
            )
            expect(mockTrackedFetch).toHaveBeenCalledTimes(20)
            expect(authHeaders.size).toBe(1)
        })

        it('expires an adopted APNS token by its own issue time, not by when this pod read it', async () => {
            const nowMs = 1_800_000_000_000
            jest.spyOn(Date, 'now').mockReturnValue(nowMs)
            const b64 = (o: object): string => Buffer.from(JSON.stringify(o)).toString('base64url')
            const fortyMinutesOld = `${b64({ alg: 'ES256', kid: 'KEY123' })}.${b64({ iss: 'TEAM456', iat: nowMs / 1000 - 40 * 60 })}.sig`
            const cacheKey = `@posthog/apns-provider-jwt/${createHash('sha256').update(`TEAM456:KEY123:${testEcKey}`).digest('hex')}`
            valkeyStore.set(cacheKey, fortyMinutesOld)

            let valkeyUp = true
            let firstReadFails = true
            const flakyValkey = {
                useClient: jest.fn((opts: { name: string }, fn: any) => {
                    if (!valkeyUp) {
                        return null
                    }
                    if (opts.name === 'apns-jwt-read' && firstReadFails) {
                        firstReadFails = false
                        return null
                    }
                    return fn({ get: (key: string) => valkeyStore.get(key) ?? null, set: mockValkeySet })
                }),
            } as any
            const pod = new PushNotificationService(
                integrationManager,
                encryptedFields,
                fetchUtils,
                flakyValkey,
                personsManager as any
            )
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 15,
            })
            mockTrackedFetch.mockClear()
            const send = (): Promise<any> =>
                pod.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                    })
                )

            await send()
            valkeyUp = false
            jest.spyOn(Date, 'now').mockReturnValue(nowMs + 10 * 60 * 1000)
            await send()

            const authHeaders = mockTrackedFetch.mock.calls.map(
                (call: any) => call[0].fetchParams.headers.Authorization
            )
            expect(authHeaders[0]).toBe(`bearer ${fortyMinutesOld}`)
            expect(authHeaders[1]).not.toBe(`bearer ${fortyMinutesOld}`)
        })

        it('keeps presenting the shared APNS token after a read misses it during a Valkey fault', async () => {
            const b64 = (o: object): string => Buffer.from(JSON.stringify(o)).toString('base64url')
            const shared = `${b64({ alg: 'ES256', kid: 'KEY123' })}.${b64({ iss: 'TEAM456', iat: Math.floor(Date.now() / 1000) })}.sig`
            const cacheKey = `@posthog/apns-provider-jwt/${createHash('sha256').update(`TEAM456:KEY123:${testEcKey}`).digest('hex')}`
            valkeyStore.set(cacheKey, shared)

            // The first send misses both reads, loses SET NX to the shared token and falls back to its own.
            const readUp = [false, false, true, false]
            const flakyValkey = {
                useClient: jest.fn((opts: { name: string }, fn: any) => {
                    if (opts.name === 'apns-jwt-read' && !readUp.shift()) {
                        return null
                    }
                    return fn({ get: (key: string) => valkeyStore.get(key) ?? null, set: mockValkeySet })
                }),
            } as any
            const pod = new PushNotificationService(
                integrationManager,
                encryptedFields,
                fetchUtils,
                flakyValkey,
                personsManager as any
            )
            mockTrackedFetch.mockResolvedValue({
                fetchError: null,
                fetchResponse: { status: 200, text: () => Promise.resolve(''), dump: () => Promise.resolve() },
                fetchDuration: 15,
            })
            mockTrackedFetch.mockClear()
            const send = (): Promise<any> =>
                pod.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                    })
                )

            await send()
            await send()
            await send()

            const authHeaders = mockTrackedFetch.mock.calls.map(
                (call: any) => call[0].fetchParams.headers.Authorization
            )
            expect(authHeaders[0]).not.toBe(`bearer ${shared}`)
            expect(authHeaders.slice(1)).toEqual([`bearer ${shared}`, `bearer ${shared}`])
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
                failingValkey,
                personsManager as any
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
            await Promise.all([send(), send(), send()])
            await send()

            const authHeaders = mockTrackedFetch.mock.calls.map(
                (call: any) => call[0].fetchParams.headers.Authorization
            )
            expect(authHeaders).toHaveLength(4)
            expect(authHeaders[0]).toEqual(expect.stringContaining('bearer '))
            expect(new Set(authHeaders).size).toBe(1)
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

        describe('when APNs rejects the provider token', () => {
            const apnsResponse = (status: number, reason?: string, headers?: Record<string, string>): any => ({
                fetchError: null,
                fetchResponse: {
                    status,
                    headers,
                    text: () => Promise.resolve(reason ? JSON.stringify({ reason }) : ''),
                    dump: () => Promise.resolve(),
                },
                fetchDuration: 10,
            })
            const send = (): Promise<any> =>
                service.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                    })
                )
            const sentTokens = (): string[] =>
                mockTrackedFetch.mock.calls.map((call: any) => call[0].fetchParams.headers.Authorization)
            const jwtCacheKey = `@posthog/apns-provider-jwt/${createHash('sha256').update(`TEAM456:KEY123:${testEcKey}`).digest('hex')}`
            const forgetSharedAcceptance = (): void => {
                for (const key of [...valkeyStore.keys()]) {
                    if (key.startsWith('@posthog/apns-key-accepted/')) {
                        valkeyStore.delete(key)
                    }
                }
            }
            const tokenIssuedMinutesAgo = (minutes: number): string =>
                `e30.${Buffer.from(JSON.stringify({ iat: Math.floor(Date.now() / 1000) - minutes * 60 })).toString('base64url')}.sig`

            beforeEach(() => {
                mockTrackedFetch.mockReset()
                valkeyStore.set(jwtCacheKey, tokenIssuedMinutesAgo(30))
            })

            it('retries a young rejected token once without replacing it', async () => {
                const youngToken = tokenIssuedMinutesAgo(1)
                valkeyStore.set(jwtCacheKey, youngToken)
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'InvalidProviderToken'))

                const result = await send()

                expect(result.error).toContain('InvalidProviderToken')
                expect(sentTokens()).toEqual([`bearer ${youngToken}`, `bearer ${youngToken}`])
                expect(valkeyStore.get(jwtCacheKey)).toBe(youngToken)
                expect([...valkeyStore.keys()].some((key) => key.includes('jwt-refresh'))).toBe(false)
            })

            it('retries a rejected device when another device of the person delivered', async () => {
                valkeyStore.set(jwtCacheKey, tokenIssuedMinutesAgo(1))
                let tokenARejected = false
                mockTrackedFetch.mockImplementation(({ url }: { url: string }) => {
                    if (url.endsWith('/token-a') && !tokenARejected) {
                        tokenARejected = true
                        return Promise.resolve(apnsResponse(403, 'InvalidProviderToken'))
                    }
                    return Promise.resolve(apnsResponse(200))
                })

                const result = await service.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        [deviceSubscriptionKey('com.example.app', 'token-a')]: encryptedFields.encrypt('token-a'),
                        [deviceSubscriptionKey('com.example.app', 'token-b')]: encryptedFields.encrypt('token-b'),
                    })
                )

                expect(result.logs.map((log: any) => log.message)).toContainEqual(
                    expect.stringContaining('accepted by APNs for 2 of 2 device(s)')
                )
                expect(mockTrackedFetch).toHaveBeenCalledTimes(3)
            })

            it.each(['InvalidProviderToken', 'ExpiredProviderToken'])(
                'retries once with a new token after %s',
                async (reason) => {
                    mockTrackedFetch
                        .mockResolvedValueOnce(apnsResponse(403, reason))
                        .mockResolvedValueOnce(apnsResponse(200))

                    const result = await send()

                    expect(result.error).toBeUndefined()
                    expect(result.metrics).toContainEqual(
                        expect.objectContaining({ metric_name: 'push_sent', count: 1 })
                    )
                    const [rejected, retried] = sentTokens()
                    expect(retried).not.toEqual(rejected)
                    expect(`bearer ${valkeyStore.get(jwtCacheKey)}`).toEqual(retried)
                }
            )

            it('signs at most one new token per refresh window for a key', async () => {
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'InvalidProviderToken'))

                const results = [await send(), await send(), await send()]

                for (const result of results) {
                    expect(result.error).toContain('InvalidProviderToken')
                }
                expect(mockTrackedFetch).toHaveBeenCalledTimes(6)
                expect(new Set(sentTokens()).size).toBe(2)
                expect(mockValkeySet).toHaveBeenCalledWith(
                    expect.stringContaining('@posthog/apns-provider-jwt-refresh/'),
                    expect.any(String),
                    'EX',
                    1200,
                    'NX'
                )
            })

            it('reschedules a rejection for a key that delivered recently instead of failing the send', async () => {
                mockTrackedFetch.mockResolvedValueOnce(apnsResponse(200))
                await send()
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'InvalidProviderToken'))

                const rescheduled = await send()
                // The retry can run on a pod that has not delivered with this key yet. Only the carried evidence counts.
                forgetSharedAcceptance()
                const otherPod = new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    mockValkey,
                    personsManager as any
                )
                const retried = await otherPod.executeSendPushNotification(rescheduled.invocation)

                for (const result of [rescheduled, retried]) {
                    expect(result.finished).toBe(false)
                    expect(result.invocation.queueScheduledAt).toBeDefined()
                    expect(result.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
                }

                // Acceptance carried for a different signing key does not make this key's rejection retriable.
                const otherKeyCarried = {
                    ...rescheduled.invocation,
                    queueMetadata: { tries: 1, apnsAcceptedKeys: ['0000000000000000'] },
                }
                const failed = await new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    mockValkey,
                    personsManager as any
                ).executeSendPushNotification(otherKeyCarried)
                expect(failed.finished).toBe(true)
                expect(failed.metrics).toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
            })

            it('reschedules a young token rejection on a pod that has not delivered with a key another pod delivered with', async () => {
                mockTrackedFetch.mockResolvedValueOnce(apnsResponse(200))
                await send()
                valkeyStore.set(jwtCacheKey, tokenIssuedMinutesAgo(1))
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'InvalidProviderToken'))

                const result = await new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    mockValkey,
                    personsManager as any
                ).executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                    })
                )

                expect(result.finished).toBe(false)
                expect(result.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
            })

            it('does not read shared acceptance for a failure a working key cannot explain', async () => {
                mockTrackedFetch.mockResolvedValue(apnsResponse(429, 'TooManyRequests'))

                await service.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        [deviceSubscriptionKey('com.example.app', 'token-a')]: encryptedFields.encrypt('token-a'),
                        [deviceSubscriptionKey('com.example.app', 'token-b')]: encryptedFields.encrypt('token-b'),
                    })
                )

                expect(mockValkey.useClient).not.toHaveBeenCalledWith(
                    expect.objectContaining({ name: 'apns-key-accepted-read' }),
                    expect.anything()
                )
            })

            it('carries the working key when another device asks for a longer Retry-After', async () => {
                mockTrackedFetch.mockResolvedValueOnce(apnsResponse(200))
                await send()
                // Only one error per channel reaches the reschedule, and the 429 wins it on Retry-After.
                mockTrackedFetch.mockImplementation(({ url }: { url: string }) =>
                    Promise.resolve(
                        url.endsWith('/token-a')
                            ? apnsResponse(403, 'InvalidProviderToken')
                            : apnsResponse(429, 'TooManyRequests', { 'retry-after': '30' })
                    )
                )
                const rescheduled = await service.executeSendPushNotification(
                    createSendPushNotificationInvocation({
                        [deviceSubscriptionKey('com.example.app', 'token-a')]: encryptedFields.encrypt('token-a'),
                        [deviceSubscriptionKey('com.example.app', 'token-b')]: encryptedFields.encrypt('token-b'),
                    })
                )
                expect(rescheduled.finished).toBe(false)

                // On a fresh pod the throttled device is gone, so only the carried evidence keeps the rejection retriable.
                forgetSharedAcceptance()
                mockTrackedFetch.mockImplementation(({ url }: { url: string }) =>
                    Promise.resolve(
                        url.endsWith('/token-a')
                            ? apnsResponse(403, 'InvalidProviderToken')
                            : apnsResponse(410, 'Unregistered')
                    )
                )
                const retried = await new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    mockValkey,
                    personsManager as any
                ).executeSendPushNotification(rescheduled.invocation)

                expect(retried.finished).toBe(false)
                expect(retried.metrics).not.toContainEqual(expect.objectContaining({ metric_name: 'push_failed' }))
            })

            it('reuses a token another pod already put in place of the rejected one', async () => {
                mockTrackedFetch
                    .mockImplementationOnce(() => {
                        valkeyStore.set(jwtCacheKey, 'token-from-another-pod')
                        return Promise.resolve(apnsResponse(403, 'InvalidProviderToken'))
                    })
                    .mockResolvedValueOnce(apnsResponse(200))

                const result = await send()

                expect(result.error).toBeUndefined()
                expect(sentTokens()[1]).toBe('bearer token-from-another-pod')
                expect(valkeyStore.get(jwtCacheKey)).toBe('token-from-another-pod')
                expect([...valkeyStore.keys()].some((key) => key.includes('jwt-refresh'))).toBe(false)
            })

            it('adopts the token another pod signs while this pod waits for the refresh claim', async () => {
                const set = mockValkeySet.getMockImplementation()!
                mockValkeySet.mockImplementation((key: string, ...rest: any[]) => {
                    if (key.includes('jwt-refresh')) {
                        valkeyStore.set(key, String(Date.now()))
                        valkeyStore.set(jwtCacheKey, 'token-from-another-pod')
                        return null
                    }
                    return set(key, ...rest)
                })
                mockTrackedFetch
                    .mockResolvedValueOnce(apnsResponse(403, 'InvalidProviderToken'))
                    .mockResolvedValueOnce(apnsResponse(200))

                const result = await send()

                expect(result.error).toBeUndefined()
                expect(sentTokens()[1]).toBe('bearer token-from-another-pod')
            })

            it('does not wait for a replacement when the refresh was claimed long ago', async () => {
                const refreshKey = jwtCacheKey.replace('apns-provider-jwt/', 'apns-provider-jwt-refresh/')
                valkeyStore.set(refreshKey, String(Date.now() - 5 * 60 * 1000))
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'InvalidProviderToken'))

                const result = await send()

                expect(result.error).toContain('InvalidProviderToken')
                const cacheReads = mockValkey.useClient.mock.calls.filter(
                    ([opts]: any) => opts.name === 'apns-jwt-read'
                )
                expect(cacheReads).toHaveLength(2)
            })

            it('signs no new tokens for a rejected key while Valkey is down', async () => {
                const pod = new PushNotificationService(
                    integrationManager,
                    encryptedFields,
                    fetchUtils,
                    { useClient: jest.fn(() => null) } as any,
                    personsManager as any
                )
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'InvalidProviderToken'))

                for (let i = 0; i < 3; i++) {
                    await pod.executeSendPushNotification(
                        createSendPushNotificationInvocation({
                            '$device_push_subscription_com.example.app': encryptedFields.encrypt('apns-device-token'),
                        })
                    )
                }

                expect(mockTrackedFetch).toHaveBeenCalledTimes(6)
                expect(new Set(sentTokens()).size).toBe(1)
            })

            it('does not retry when the rejection is not about the provider token', async () => {
                mockTrackedFetch.mockResolvedValue(apnsResponse(403, 'TopicDisallowed'))

                const result = await send()

                expect(result.error).toContain('TopicDisallowed')
                expect(mockTrackedFetch).toHaveBeenCalledTimes(1)
            })
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

    describe('multiple devices on one app', () => {
        const twoDevices = () =>
            createSendPushNotificationInvocation({
                [deviceSubscriptionKey('test-project', 'token-phone')]: encryptedFields.encrypt('token-phone'),
                [deviceSubscriptionKey('test-project', 'token-tablet')]: encryptedFields.encrypt('token-tablet'),
            })

        const ok = () => ({
            fetchError: null,
            fetchResponse: { status: 200, text: () => Promise.resolve('{}'), dump: () => Promise.resolve() },
            fetchDuration: 10,
        })

        const unregistered = () => ({
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

        const serverError = () => ({
            fetchError: null,
            fetchResponse: { status: 500, text: () => Promise.resolve('{}'), dump: () => Promise.resolve() },
            fetchDuration: 10,
        })

        it('sends to every device, not just one', async () => {
            // The bug: a second device on the same app was unreachable because it overwrote the first.
            mockTrackedFetch.mockResolvedValue(ok())

            const result = await service.executeSendPushNotification(twoDevices())

            expect(result.error).toBeUndefined()
            const sentTokens = mockTrackedFetch.mock.calls.map(
                (call: any) => parseJSON(call[0].fetchParams.body).message.token
            )
            expect(sentTokens.sort()).toEqual(['token-phone', 'token-tablet'])
        })

        it('prunes only the dead device and still delivers to the other', async () => {
            mockTrackedFetch.mockResolvedValueOnce(unregistered()).mockResolvedValueOnce(ok())

            const result = await service.executeSendPushNotification(twoDevices())

            expect(result.error).toBeUndefined()
            const unsets = result.capturedPostHogEvents.flatMap((e: any) => e.properties.$unset ?? [])
            expect(unsets).toHaveLength(1)
            expect(unsets[0]).toMatch(/^\$device_push_subscription_test-project:/)
        })

        it('does not contact a pruned device again when the step is retried', async () => {
            // The dead key has to leave the invocation's own snapshot as well as the person. The retry
            // reads that snapshot back, so a key left behind means another send to the dead token and a
            // second $unset for it.
            mockTrackedFetch.mockImplementation((opts: any) =>
                Promise.resolve(
                    parseJSON(opts.fetchParams.body).message.token === 'token-phone' ? unregistered() : serverError()
                )
            )

            const first = await service.executeSendPushNotification(twoDevices())
            expect(first.finished).toBe(false)

            mockTrackedFetch.mockClear()
            mockTrackedFetch.mockImplementation(() => Promise.resolve(ok()))

            const retry = await service.executeSendPushNotification(first.invocation)

            const retriedTokens = mockTrackedFetch.mock.calls.map(
                (call: any) => parseJSON(call[0].fetchParams.body).message.token
            )
            expect(retriedTokens).toEqual(['token-tablet'])
            expect(retry.capturedPostHogEvents).toEqual([])
        })

        it('does not retry the step when one device failed but another was delivered to', async () => {
            // Retrying would push a second time to the device that already received it. Losing the
            // failed device's notification is the better of the two outcomes.
            mockTrackedFetch.mockResolvedValueOnce(ok()).mockResolvedValueOnce(serverError())

            const result = await service.executeSendPushNotification(twoDevices())

            // Finished, not rescheduled: a reschedule is what would resend to the delivered device.
            expect(result.error).toBeUndefined()
            expect(result.finished).toBe(true)
            expect(result.invocation.queueScheduledAt).toBeUndefined()
        })

        it('reschedules the step when no device was delivered to', async () => {
            // Nothing arrived anywhere, so a retry cannot duplicate a delivery.
            mockTrackedFetch.mockResolvedValue(serverError())

            const result = await service.executeSendPushNotification(twoDevices())

            expect(result.finished).toBe(false)
            expect(result.invocation.queueScheduledAt).toBeDefined()
        })

        const badPayload = () => ({
            fetchError: null,
            fetchResponse: { status: 400, text: () => Promise.resolve('{}'), dump: () => Promise.resolve() },
            fetchDuration: 10,
        })

        it.each([
            [
                'transient first',
                () => mockTrackedFetch.mockResolvedValueOnce(serverError()).mockResolvedValueOnce(badPayload()),
            ],
            [
                'terminal first',
                () => mockTrackedFetch.mockResolvedValueOnce(badPayload()).mockResolvedValueOnce(serverError()),
            ],
        ])('reschedules when one device failed transiently and another terminally, %s', async (_name, arrange) => {
            // Whether the step is worth re-running depends on any device being retriable, not on which
            // device happened to fail last. Keeping only the last error made this order-dependent, so
            // a terminal failure arriving second dropped the retry the transient one had earned.
            arrange()

            const result = await service.executeSendPushNotification(twoDevices())

            expect(result.finished).toBe(false)
            expect(result.invocation.queueScheduledAt).toBeDefined()
        })

        const throttled = () => ({
            fetchError: null,
            fetchResponse: {
                status: 429,
                headers: { 'retry-after': '30' },
                text: () => Promise.resolve('{}'),
                dump: () => Promise.resolve(),
            },
            fetchDuration: 10,
        })

        it.each([
            [
                'throttled device second',
                () => mockTrackedFetch.mockResolvedValueOnce(serverError()).mockResolvedValueOnce(throttled()),
            ],
            [
                'throttled device first',
                () => mockTrackedFetch.mockResolvedValueOnce(throttled()).mockResolvedValueOnce(serverError()),
            ],
        ])('reschedules using the longest Retry-After across devices, %s', async (_name, arrange) => {
            // Only one error per channel reaches the reschedule, so the loop has to hand up the device
            // asking for the longest wait. Handing up the 500 instead drops the 30s window to a sub-2s
            // backoff, and the retries then burn inside the window the provider asked us to sit out.
            arrange()

            const result = await service.executeSendPushNotification(twoDevices())

            expect(result.finished).toBe(false)
            const delayMs = result.invocation.queueScheduledAt!.toMillis() - Date.now()
            expect(delayMs).toBeGreaterThan(20_000)
            expect(delayMs).toBeLessThanOrEqual(30_000)
        })

        it('explains a device that failed while another device was delivered to', async () => {
            // The channel reports success, so this device never reaches the outer catch that logs a
            // channel failure. Without a line of its own it is permanently broken and invisible, since
            // the only other record is the debug-level provider response.
            mockTrackedFetch.mockResolvedValueOnce(ok()).mockResolvedValueOnce(badPayload())

            const result = await service.executeSendPushNotification(twoDevices())

            expect(result.finished).toBe(true)
            const visibleLogs = result.logs.filter((log) => log.level !== 'debug').map((log) => log.message)
            expect(visibleLogs).toContainEqual(expect.stringContaining('rejected the notification contents'))
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

        it('logs a skipped channel at info and reports channel counts when another channel delivered', async () => {
            ;(integrationManager.get as jest.Mock).mockImplementation((id: number) =>
                Promise.resolve(id === 1 ? firebaseIntegration : apnsIntegration)
            )
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('fcm-token'),
            })
            invocation.queueParameters = { ...invocation.queueParameters, integrationIds: [1, 2] } as any
            mockTrackedFetch.mockResolvedValue(ok200)

            const result = await service.executeSendPushNotification(invocation)

            expect(result.logs).toContainEqual(
                expect.objectContaining({
                    level: 'info',
                    message: expect.stringContaining('No active APNS device token found'),
                })
            )
            expect(result.logs.filter((log) => log.level === 'warn')).toEqual([])
            expect(result.execResult).toEqual({ delivered: 1, skipped: 1, failed: 0 })
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
