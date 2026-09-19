import { PushSubscriptionsService } from './push-subscriptions.service'

describe('PushSubscriptionsService', () => {
    const team = { id: 7, api_token: 'phc_real', secret_api_token: null, secret_api_token_backup: null }

    let teamManager: any
    let postgres: any
    let internalCapture: any
    let integrationRows: { config: Record<string, any> }[]
    let service: PushSubscriptionsService

    const request = (body: unknown, method = 'POST') => ({
        method,
        body: Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)),
    })

    const valid = {
        api_key: 'phc_real',
        distinct_id: 'user-1',
        device_token: 'device-1',
        app_id: 'my-firebase-project',
    }

    beforeEach(() => {
        integrationRows = [{ config: { project_id: 'my-firebase-project' } }]
        teamManager = {
            getTeamByToken: jest.fn((token: string) => Promise.resolve(token === 'phc_real' ? team : null)),
        }
        postgres = { query: jest.fn(() => Promise.resolve({ rows: integrationRows })) }
        internalCapture = { capture: jest.fn(() => Promise.resolve({ status: 200 })) }
        service = new PushSubscriptionsService(
            teamManager,
            postgres,
            { encrypt: (value: string) => `enc:${value}` } as any,
            internalCapture,
            'secret'
        )
    })

    it('stores the encrypted device token under the app id', async () => {
        const result = await service.handle(request(valid))

        expect(result.status).toEqual(200)
        expect(internalCapture.capture).toHaveBeenCalledWith(
            expect.objectContaining({
                properties: expect.objectContaining({
                    $set: { '$device_push_subscription_my-firebase-project': 'enc:device-1' },
                }),
            })
        )
    })

    it('reports a rejected capture rather than telling the SDK the token was stored', async () => {
        // The SDK marks a registration delivered on a 2xx and stops re-sending it, so a capture that
        // did not happen has to surface as an error or the device is never registered.
        internalCapture.capture.mockResolvedValue({ status: 503 })

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(500)
        expect(result.body).toMatchObject({ code: 'capture_failed' })
    })

    it('acknowledges a registration for an app with no channel without storing it', async () => {
        // SDKs register on every app open, so a 4xx here would turn every such project into an
        // error firehose that never stops.
        integrationRows = []

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(200)
        expect(result.body).toEqual({ distinct_id: 'user-1', stored: false, push_enabled: false })
        expect(internalCapture.capture).not.toHaveBeenCalled()
    })

    it('unsets the property on DELETE even when the channel is gone', async () => {
        integrationRows = []

        const result = await service.handle(request(valid, 'DELETE'))

        expect(result.status).toEqual(200)
        expect(internalCapture.capture).toHaveBeenCalledWith(
            expect.objectContaining({
                properties: expect.objectContaining({ $unset: ['$device_push_subscription_my-firebase-project'] }),
            })
        )
    })

    it('rejects a body over the size limit before parsing it', async () => {
        const oversized = Buffer.alloc(16 * 1024 + 1, 'a')

        const result = await service.handle({ method: 'POST', body: oversized })

        expect(result.status).toEqual(413)
        expect(result.body).toMatchObject({ code: 'request_too_large' })
    })

    it('names each missing field and how it was missing', async () => {
        const result = await service.handle(request({ api_key: 'phc_real', device_token: '', app_id: 12 }))

        expect(result.status).toEqual(400)
        expect(result.rejection?.detail).toEqual('distinct_id:absent,device_token:empty,app_id:invalid')
    })

    it.each([
        ['api_key', { api_key: 'phc_real' }],
        ['token', { token: 'phc_real' }],
        ['$token', { $token: 'phc_real' }],
        ['properties.token', { properties: { token: 'phc_real' } }],
    ])('accepts the project token under %s', async (_name, carrier) => {
        const result = await service.handle(request({ ...valid, api_key: undefined, ...carrier }))

        expect(result.status).toEqual(200)
    })

    it('stops asking the database for a token that resolved to nothing', async () => {
        const first = await service.handle(request({ ...valid, api_key: 'phc_unknown' }))
        const second = await service.handle(request({ ...valid, api_key: 'phc_unknown' }))

        expect(first.status).toEqual(401)
        expect(second.status).toEqual(401)
        expect(teamManager.getTeamByToken).toHaveBeenCalledTimes(1)
    })

    it('reads the channel per request so a policy change applies immediately', async () => {
        // The row carries the identity verification mode. A cached copy would keep answering
        // `disabled` after an admin turns verification on, and store registrations unverified.
        await service.handle(request(valid))
        integrationRows = [{ config: { project_id: 'my-firebase-project', push_identity_verification: 'required' } }]

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(401)
        expect(result.body).toMatchObject({ code: 'identity_verification_failed' })
    })
})
