import { generateKeyPairSync } from 'crypto'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleInvocation, createHogFunction } from '~/cdp/_tests/fixtures'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { parseJSON } from '~/common/utils/json-parse'

import { IntegrationManagerService } from '../managers/integration-manager.service'
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
        integrationId: 1,
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
        }

        service = new PushNotificationService(integrationManager, encryptedFields, fetchUtils)
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

        it('sets error when push fails', async () => {
            const invocation = createSendPushNotificationInvocation({
                '$device_push_subscription_test-project': encryptedFields.encrypt('device-token-123'),
            })
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

            expect(result.error).toBeTruthy()
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
    })
})
