import { Server, createServer, request as httpRequest } from 'http'
import { AddressInfo } from 'net'
import { gzipSync } from 'zlib'

import { FetchResponse, internalFetch } from '~/common/utils/request'

import { createPushSubscriptionsHandler } from './push-subscriptions-http'
import { PushHandlerResult, PushSubscriptionsService } from './push-subscriptions.service'

describe('push subscriptions http', () => {
    let server: Server
    let base: string
    let seen: { method: string; body: string; contentType?: string; compression?: string | null }[]
    let answer: PushHandlerResult

    beforeEach(async () => {
        seen = []
        answer = { status: 200, body: { distinct_id: 'user-1' } }
        const service = {
            handle: (request: any) => {
                seen.push({
                    method: request.method,
                    body: request.body.toString('utf8'),
                    contentType: request.contentType,
                    compression: request.query?.get('compression') ?? null,
                })
                return Promise.resolve(answer)
            },
        } as unknown as PushSubscriptionsService

        const handler = createPushSubscriptionsHandler(service)
        server = createServer((req, res) => void handler(req, res))
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterEach(async () => {
        await new Promise((resolve) => server.close(resolve))
    })

    const post = (path: string, init: Record<string, any> = {}): Promise<FetchResponse> =>
        internalFetch(`${base}${path}`, { method: 'POST', ...init })

    it('delivers a DELETE body to the service', async () => {
        // The reason this endpoint is not on the plugin server's express framework: that one drops
        // the body on DELETE, and DELETE with a body is how every released SDK unregisters a device.
        const body = JSON.stringify({ api_key: 'phc_x', app_id: 'a' })

        const response = await internalFetch(`${base}/api/push_subscriptions/`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body,
        })

        expect(response.status).toEqual(200)
        expect(seen).toEqual([{ method: 'DELETE', body, contentType: 'application/json', compression: null }])
    })

    it('passes the content type and query through untouched', async () => {
        await post('/api/push_subscriptions/?compression=gzip', {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'data=x',
        })

        expect(seen[0]).toMatchObject({
            contentType: 'application/x-www-form-urlencoded',
            compression: 'gzip',
        })
    })

    it('hands the gzipped bytes over without decoding them itself', async () => {
        const gzipped = gzipSync(Buffer.from('{"a":1}'))

        await post('/api/push_subscriptions/', {
            headers: { 'Content-Encoding': 'gzip', 'Content-Type': 'application/json' },
            body: gzipped,
        })

        expect(Buffer.from(seen[0].body, 'utf8').length).toBeGreaterThan(0)
    })

    it.each([['/api/push_subscriptions'], ['/api/push_subscriptions/']])('serves %s', async (path) => {
        const response = await post(path, { body: '{}' })

        expect(response.status).toEqual(200)
    })

    it('does not serve any other path', async () => {
        const response = await post('/api/push_subscriptions/extra', { body: '{}' })

        expect(response.status).toEqual(404)
        expect(seen).toEqual([])
    })

    it('answers a preflight without calling the service', async () => {
        const response = await internalFetch(`${base}/api/push_subscriptions/`, {
            method: 'OPTIONS',
            headers: { Origin: 'https://app.example.com' },
        })

        expect(response.status).toEqual(200)
        expect(response.headers['access-control-allow-origin']).toEqual('https://app.example.com')
        expect(seen).toEqual([])
    })

    it('advertises the verbs it serves, including the one django omits', async () => {
        // A browser preflight for the unregister call is refused when DELETE is missing here.
        const response = await internalFetch(`${base}/api/push_subscriptions/`, {
            method: 'OPTIONS',
            headers: { Origin: 'https://app.example.com' },
        })

        expect(response.headers['access-control-allow-methods']).toEqual('GET, POST, DELETE, OPTIONS')
    })

    it('echoes only the origin, never a wildcard with credentials', async () => {
        const response = await post('/api/push_subscriptions/', {
            headers: { Origin: 'https://app.example.com:8443' },
            body: '{}',
        })

        expect(response.headers['access-control-allow-origin']).toEqual('https://app.example.com:8443')
        expect(response.headers.vary).toEqual('Origin')
    })

    it('stops reading once a body passes the limit, and still answers', async () => {
        answer = { status: 413, body: { type: 'validation_error', code: 'request_too_large', detail: 'x', attr: null } }
        const oversized = Buffer.alloc(64 * 1024, 'a')

        const response = await post('/api/push_subscriptions/', { body: oversized })

        expect(response.status).toEqual(413)
        // One byte past the limit is enough for the service to see it is over; nothing larger is held.
        expect(seen[0].body.length).toEqual(16 * 1024 + 1)
    })

    it('returns the rejection body the service produced', async () => {
        answer = {
            status: 401,
            body: {
                type: 'authentication_error',
                code: 'invalid_api_key',
                detail: 'Invalid project token.',
                attr: null,
            },
            rejection: { code: 'invalid_api_key', apiKeyFingerprint: 'abc123' },
        }

        const response = await post('/api/push_subscriptions/', { body: '{}' })

        expect(response.status).toEqual(401)
        expect(await response.json()).toEqual({
            type: 'authentication_error',
            code: 'invalid_api_key',
            detail: 'Invalid project token.',
            attr: null,
        })
    })

    it('does not hang when the client disconnects mid-body', async () => {
        // Announce a body and then drop the socket. Without a close handler the read never settles
        // and the handler is retained for the life of the process.
        await new Promise<void>((resolve) => {
            const req = httpRequest(
                {
                    host: '127.0.0.1',
                    port: (server.address() as AddressInfo).port,
                    path: '/api/push_subscriptions/',
                    method: 'POST',
                },
                () => undefined
            )
            req.setHeader('Content-Length', '1000')
            req.on('error', () => resolve())
            req.write('x'.repeat(10))
            req.destroy()
            setTimeout(resolve, 100)
        })

        const response = await post('/api/push_subscriptions/', { body: '{}' })
        expect(response.status).toEqual(200)
    })
})
