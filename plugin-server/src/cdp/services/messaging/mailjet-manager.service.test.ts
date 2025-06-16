import crypto from 'crypto'
import express from 'express'

import { Hub } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { MessagingMailjetManagerService } from './mailjet-manager.service'

describe('MessagingMailjetManagerService', () => {
    let service: MessagingMailjetManagerService
    let mockHub: Hub
    const secretKey = 'test-secret-key'

    beforeEach(() => {
        mockHub = {
            MAILJET_SECRET_KEY: secretKey,
        } as Hub
        service = new MessagingMailjetManagerService(mockHub)
    })

    describe('handleWebhook', () => {
        it('should return 403 if required headers are missing', async () => {
            const req = {
                headers: {},
                rawBody: Buffer.from('test'),
                get: () => undefined,
                header: () => undefined,
                accepts: () => false,
                acceptsCharsets: () => false,
                acceptsEncodings: () => false,
                acceptsLanguages: () => false,
                param: () => undefined,
                is: () => false,
                protocol: 'http',
                ip: '127.0.0.1',
                ips: [],
                subdomains: [],
                path: '/',
                hostname: 'localhost',
                host: 'localhost',
                fresh: false,
                stale: true,
                xhr: false,
                body: {},
                cookies: {},
                method: 'POST',
                params: {},
                query: {},
                route: {},
                secure: false,
                signedCookies: {},
                originalUrl: '/',
                url: '/',
                baseUrl: '/',
            } as unknown as express.Request & { rawBody?: Buffer }

            const result = await service.handleWebhook(req)
            expect(result.status).toBe(403)
            expect(result.message).toBe('Missing required headers or body')
        })

        it('should return 403 if signature is invalid', async () => {
            const timestamp = Date.now().toString()
            const payload = 'test-payload'
            const req = {
                headers: {
                    'x-mailjet-signature': 'invalid-signature',
                    'x-mailjet-timestamp': timestamp,
                },
                rawBody: Buffer.from(payload),
                body: {
                    event: 'sent',
                    time: Date.now(),
                    email: 'test@example.com',
                    mj_campaign_id: 1,
                    mj_contact_id: 1,
                    message_id: 'test-message-id',
                    custom_id: 'test-custom-id',
                    payload: {},
                },
                get: () => undefined,
                header: () => undefined,
                accepts: () => false,
                acceptsCharsets: () => false,
                acceptsEncodings: () => false,
                acceptsLanguages: () => false,
                param: () => undefined,
                is: () => false,
                protocol: 'http',
                ip: '127.0.0.1',
                ips: [],
                subdomains: [],
                path: '/',
                hostname: 'localhost',
                host: 'localhost',
                fresh: false,
                stale: true,
                xhr: false,
                cookies: {},
                method: 'POST',
                params: {},
                query: {},
                route: {},
                secure: false,
                signedCookies: {},
                originalUrl: '/',
                url: '/',
                baseUrl: '/',
            } as unknown as express.Request & { rawBody?: Buffer }

            const result = await service.handleWebhook(req)
            expect(result.status).toBe(403)
            expect(result.message).toBe('Invalid signature')
        })

        it('should process valid webhook events', async () => {
            const timestamp = Date.now().toString()
            const payload = JSON.stringify({
                event: 'sent',
                time: Date.now(),
                email: 'test@example.com',
                mj_campaign_id: 1,
                mj_contact_id: 1,
                message_id: 'test-message-id',
                custom_id: 'test-custom-id',
                payload: {},
            })
            const signature = crypto.createHmac('sha256', secretKey).update(`${timestamp}.${payload}`).digest('hex')

            const req = {
                headers: {
                    'x-mailjet-signature': signature,
                    'x-mailjet-timestamp': timestamp,
                },
                rawBody: Buffer.from(payload),
                body: parseJSON(payload),
                get: () => undefined,
                header: () => undefined,
                accepts: () => false,
                acceptsCharsets: () => false,
                acceptsEncodings: () => false,
                acceptsLanguages: () => false,
                param: () => undefined,
                is: () => false,
                protocol: 'http',
                ip: '127.0.0.1',
                ips: [],
                subdomains: [],
                path: '/',
                hostname: 'localhost',
                host: 'localhost',
                fresh: false,
                stale: true,
                xhr: false,
                cookies: {},
                method: 'POST',
                params: {},
                query: {},
                route: {},
                secure: false,
                signedCookies: {},
                originalUrl: '/',
                url: '/',
                baseUrl: '/',
            } as unknown as express.Request & { rawBody?: Buffer }

            const result = await service.handleWebhook(req)
            expect(result.status).toBe(200)
            expect(result.message).toBe('OK')
        })

        it('should handle different event types', async () => {
            const timestamp = Date.now().toString()
            const events = [
                {
                    event: 'open',
                    ip: '127.0.0.1',
                    geo: 'US',
                    agent: 'Mozilla',
                },
                {
                    event: 'click',
                    url: 'https://example.com',
                },
                {
                    event: 'bounce',
                    blocked: false,
                    hard_bounce: true,
                    error: 'test error',
                },
                {
                    event: 'spam',
                    source: 'test source',
                },
                {
                    event: 'unsub',
                    mj_list_id: '123',
                },
            ]

            for (const eventData of events) {
                const payload = JSON.stringify({
                    ...eventData,
                    time: Date.now(),
                    email: 'test@example.com',
                    mj_campaign_id: 1,
                    mj_contact_id: 1,
                    message_id: 'test-message-id',
                    custom_id: 'test-custom-id',
                    payload: {},
                })
                const signature = crypto.createHmac('sha256', secretKey).update(`${timestamp}.${payload}`).digest('hex')

                const req = {
                    headers: {
                        'x-mailjet-signature': signature,
                        'x-mailjet-timestamp': timestamp,
                    },
                    rawBody: Buffer.from(payload),
                    body: parseJSON(payload),
                    get: () => undefined,
                    header: () => undefined,
                    accepts: () => false,
                    acceptsCharsets: () => false,
                    acceptsEncodings: () => false,
                    acceptsLanguages: () => false,
                    param: () => undefined,
                    is: () => false,
                    protocol: 'http',
                    ip: '127.0.0.1',
                    ips: [],
                    subdomains: [],
                    path: '/',
                    hostname: 'localhost',
                    host: 'localhost',
                    fresh: false,
                    stale: true,
                    xhr: false,
                    cookies: {},
                    method: 'POST',
                    params: {},
                    query: {},
                    route: {},
                    secure: false,
                    signedCookies: {},
                    originalUrl: '/',
                    url: '/',
                    baseUrl: '/',
                } as unknown as express.Request & { rawBody?: Buffer }

                const result = await service.handleWebhook(req)
                expect(result.status).toBe(200)
                expect(result.message).toBe('OK')
            }
        })
    })
})
