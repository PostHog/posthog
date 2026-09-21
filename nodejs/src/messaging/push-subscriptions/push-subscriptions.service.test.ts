import { gzipSync } from 'zlib'

import { PushSubscriptionsService } from './push-subscriptions.service'

describe('PushSubscriptionsService', () => {
    const team = { id: 7, api_token: 'phc_real', secret_api_token: null, secret_api_token_backup: null }

    let teamManager: any
    let postgres: any
    let capture: any
    let integrationRows: { kind: string; config: Record<string, any> }[]
    let appIdQueries: number
    let integrationQueries: number
    let service: PushSubscriptionsService

    const request = (body: unknown, method = 'POST', extra: Record<string, any> = {}): any => ({
        method,
        body: Buffer.isBuffer(body) ? body : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)),
        ...extra,
    })

    const valid = {
        api_key: 'phc_real',
        distinct_id: 'user-1',
        device_token: 'device-1',
        app_id: 'my-firebase-project',
    }

    beforeEach(() => {
        integrationRows = [{ kind: 'firebase', config: { project_id: 'my-firebase-project' } }]
        appIdQueries = 0
        integrationQueries = 0
        teamManager = {
            getTeamByToken: jest.fn((token: string) => Promise.resolve(token === 'phc_real' ? team : null)),
        }
        postgres = {
            query: jest.fn((_use: unknown, query: string) => {
                if (query.includes('kind = ANY')) {
                    appIdQueries += 1
                    return Promise.resolve({ rows: integrationRows })
                }
                integrationQueries += 1
                return Promise.resolve({ rows: integrationRows })
            }),
        }
        capture = { capture: jest.fn(() => Promise.resolve()) }
        service = new PushSubscriptionsService(
            teamManager,
            postgres,
            { encrypt: (value: string) => `enc:${value}` } as any,
            capture,
            'secret'
        )
    })

    const capturedProperties = (): any => capture.capture.mock.calls[0][0].properties

    it('stores the encrypted device token under the app id', async () => {
        const result = await service.handle(request(valid))

        expect(result.status).toEqual(200)
        expect(result.body).toEqual({ distinct_id: 'user-1' })
        expect(capturedProperties().$set).toEqual({ '$device_push_subscription_my-firebase-project': 'enc:device-1' })
    })

    it('reports a rejected capture rather than telling the SDK the token was stored', async () => {
        // The SDK marks a registration delivered on a 2xx and stops re-sending it, so a capture that
        // did not happen has to surface as an error or the device is never registered.
        capture.capture.mockRejectedValue(new Error('capture returned 503'))

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(500)
        expect(result.body).toMatchObject({ code: 'capture_failed' })
    })

    it('reports a capture that threw', async () => {
        capture.capture.mockRejectedValue(new Error('connection refused'))

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(500)
        expect(result.rejection?.error).not.toBeUndefined()
    })

    it('tells a project with no channel why nothing was stored', async () => {
        // SDKs register on every app open, so a 4xx here would turn every such project into an
        // error firehose that never stops. The body carries what the status code cannot.
        integrationRows = []

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(200)
        expect(result.body).toEqual({
            distinct_id: 'user-1',
            stored: false,
            push_enabled: false,
            reason: 'no_push_channel_for_app_id',
            detail: expect.stringContaining("no push channel for app_id 'my-firebase-project'"),
        })
        expect(capture.capture).not.toHaveBeenCalled()
    })

    it('unsets the property on DELETE even when the channel is gone', async () => {
        integrationRows = []

        const result = await service.handle(request(valid, 'DELETE'))

        expect(result.status).toEqual(200)
        expect(capturedProperties().$unset).toEqual(['$device_push_subscription_my-firebase-project'])
    })

    it('rejects a body over the size limit before parsing it', async () => {
        const oversized = Buffer.alloc(16 * 1024 + 1, 'a')

        const result = await service.handle({ method: 'POST', body: oversized })

        expect(result.status).toEqual(413)
        expect(result.body).toMatchObject({ code: 'request_too_large' })
    })

    it('accepts a body exactly at the size limit', async () => {
        const padding = 'a'.repeat(16 * 1024 - JSON.stringify({ ...valid, pad: '' }).length)
        const body = Buffer.from(JSON.stringify({ ...valid, pad: padding }))
        expect(body.length).toEqual(16 * 1024)

        const result = await service.handle({ method: 'POST', body })

        expect(result.status).toEqual(200)
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

    it.each([
        ['a string', 'not-an-object'],
        ['an array', ['token']],
        ['a number', 7],
    ])('treats a non-object `properties` of %s as carrying no token', async (_name, properties) => {
        // Django calls .get on it and answers 500. A request that named no token should be told so.
        const result = await service.handle(request({ ...valid, api_key: undefined, properties }))

        expect(result.status).toEqual(401)
        expect(result.body).toMatchObject({ code: 'missing_api_key' })
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
        integrationRows = [
            {
                kind: 'firebase',
                config: { project_id: 'my-firebase-project', push_identity_verification: 'required' },
            },
        ]

        const result = await service.handle(request(valid))

        expect(result.status).toEqual(401)
        expect(result.body).toMatchObject({ code: 'identity_verification_failed' })
    })

    describe('the configured app_id cache', () => {
        it('skips the channel lookup for an app_id the team has never configured', async () => {
            const first = await service.handle(request({ ...valid, app_id: 'never-configured' }))
            const queriesAfterFirst = integrationQueries
            const second = await service.handle(request({ ...valid, app_id: 'never-configured' }))

            expect(first.body).toMatchObject({ reason: 'no_push_channel_for_app_id' })
            expect(second.body).toMatchObject({ reason: 'no_push_channel_for_app_id' })
            expect(appIdQueries).toEqual(1)
            // The second request answered from the cached list rather than querying again.
            expect(integrationQueries).toEqual(queriesAfterFirst)
        })

        it('still looks the channel up for an app_id the team has configured', async () => {
            await service.handle(request(valid))
            await service.handle(request(valid))

            expect(integrationQueries).toEqual(2)
        })

        it('falls through to the real lookup when the cached list cannot be read', async () => {
            // "Don't know" must not discard a registration the team is entitled to.
            postgres.query.mockImplementation((_use: unknown, query: string) => {
                if (query.includes('kind = ANY')) {
                    return Promise.reject(new Error('read replica down'))
                }
                return Promise.resolve({ rows: integrationRows })
            })

            const result = await service.handle(request(valid))

            expect(result.status).toEqual(200)
            expect(result.body).toEqual({ distinct_id: 'user-1' })
        })
    })

    describe('request decoding', () => {
        it('accepts a gzipped body', async () => {
            const result = await service.handle(
                request(gzipSync(Buffer.from(JSON.stringify(valid))), 'POST', { contentEncoding: 'gzip' })
            )

            expect(result.status).toEqual(200)
        })

        it('accepts a gzipped body that did not declare itself', async () => {
            const result = await service.handle(request(gzipSync(Buffer.from(JSON.stringify(valid)))))

            expect(result.status).toEqual(200)
        })

        it('accepts the compression named in the query string', async () => {
            const result = await service.handle(
                request(gzipSync(Buffer.from(JSON.stringify(valid))), 'POST', {
                    query: new URLSearchParams('compression=gzip-js'),
                })
            )

            expect(result.status).toEqual(200)
        })

        it('accepts a base64 body', async () => {
            const encoded = Buffer.from(JSON.stringify(valid)).toString('base64')

            const result = await service.handle(request(Buffer.from(encoded)))

            expect(result.status).toEqual(200)
        })

        it('accepts a form-encoded body carrying the token as a field', async () => {
            const form = new URLSearchParams({
                api_key: 'phc_real',
                data: JSON.stringify({ distinct_id: 'user-1', device_token: 'device-1', app_id: valid.app_id }),
            })

            const result = await service.handle(
                request(Buffer.from(form.toString()), 'POST', {
                    contentType: 'application/x-www-form-urlencoded',
                })
            )

            expect(result.status).toEqual(200)
        })

        it.each([
            ['malformed JSON', '{"api_key":'],
            ['an array body', '[]'],
            ['a bare string', '"a string"'],
            ['an empty body', ''],
            ['a truncated gzip stream', gzipSync(Buffer.from('{"a":1}')).subarray(0, 8).toString('latin1')],
        ])('rejects %s as an invalid body', async (_name, body) => {
            const result = await service.handle(request(Buffer.from(body, 'latin1')))

            expect(result.status).toEqual(400)
            expect(result.body).toMatchObject({ code: 'invalid_json' })
        })

        it('reads a body carrying the constants python accepts and javascript does not', async () => {
            const body = `{"api_key":"phc_real","distinct_id":"user-1","device_token":"device-1","app_id":"${valid.app_id}","retries":NaN}`

            const result = await service.handle(request(Buffer.from(body)))

            expect(result.status).toEqual(200)
        })

        it('does not rewrite a string whose contents look like those constants', async () => {
            const result = await service.handle(request({ ...valid, distinct_id: 'NaN' }))

            expect(result.status).toEqual(200)
            expect(capturedProperties().$set).not.toBeUndefined()
            expect(capture.capture.mock.calls[0][0].distinctId).toEqual('NaN')
        })
    })

    describe('hostile and unusual values', () => {
        it('keys the property on a unicode app id', async () => {
            const appId = 'com.example.🚀café'
            integrationRows = [{ kind: 'firebase', config: { project_id: appId } }]

            const result = await service.handle(request({ ...valid, app_id: appId }))

            expect(result.status).toEqual(200)
            expect(capturedProperties().$set).toEqual({ [`$device_push_subscription_${appId}`]: 'enc:device-1' })
        })

        it('does not let a body define fields through the prototype', async () => {
            const body = '{"__proto__":{"api_key":"phc_real"},"distinct_id":"user-1"}'

            const result = await service.handle(request(Buffer.from(body)))

            expect(result.status).toEqual(401)
            expect(result.body).toMatchObject({ code: 'missing_api_key' })
            expect(({} as any).api_key).toBeUndefined()
        })

        it('does not read a required field off the prototype chain', async () => {
            const body = '{"api_key":"phc_real","distinct_id":"user-1","device_token":"device-1"}'

            const result = await service.handle(request(Buffer.from(body)))

            expect(result.rejection?.detail).toEqual('app_id:absent')
        })

        it('takes the last value when a field is repeated', async () => {
            const body = `{"api_key":"phc_real","distinct_id":"first","distinct_id":"second","device_token":"device-1","app_id":"${valid.app_id}"}`

            const result = await service.handle(request(Buffer.from(body)))

            expect(result.body).toEqual({ distinct_id: 'second' })
        })

        it.each([
            ['GET', 405],
            ['PUT', 405],
            ['PATCH', 405],
            ['TRACE', 405],
        ])('refuses %s', async (method, status) => {
            const result = await service.handle(request(valid, method))

            expect(result.status).toEqual(status)
            expect(result.body).toMatchObject({ code: 'method_not_allowed' })
        })
    })

    describe('identity verification', () => {
        beforeEach(() => {
            integrationRows = [
                {
                    kind: 'firebase',
                    config: { project_id: 'my-firebase-project', push_identity_verification: 'optional' },
                },
            ]
        })

        it('stores an unverified registration in optional mode and records the outcome', async () => {
            const result = await service.handle(request(valid))

            expect(result.status).toEqual(200)
            expect(result.identityVerification).toEqual({
                mode: 'optional',
                operation: 'register',
                outcome: 'unverified',
            })
        })

        it('records the outcome for an unregister too', async () => {
            const result = await service.handle(request(valid, 'DELETE'))

            expect(result.identityVerification).toMatchObject({ operation: 'unregister' })
        })

        it('takes the strictest mode when two channels share an app_id', async () => {
            // Nothing constrains two integrations to one app_id, so a lax duplicate must not be able
            // to downgrade a sibling's required policy.
            integrationRows = [
                {
                    kind: 'firebase',
                    config: { project_id: 'my-firebase-project', push_identity_verification: 'disabled' },
                },
                {
                    kind: 'apns',
                    config: { bundle_id: 'my-firebase-project', push_identity_verification: 'required' },
                },
            ]

            const result = await service.handle(request(valid))

            expect(result.status).toEqual(401)
            expect(result.body).toMatchObject({ code: 'identity_verification_failed' })
        })
    })
})
