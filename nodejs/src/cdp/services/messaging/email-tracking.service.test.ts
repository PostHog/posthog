import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFunctionType } from '~/cdp/types'
import { defaultConfig } from '~/config/config'
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'

import { Hub, Team } from '../../../types'
import { PIXEL_GIF, addTrackingToEmail, decodeHtmlEntitiesInHref } from './email-tracking.service'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('EmailTrackingService', () => {
    let hub: Hub
    let team: Team

    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub.postgres)

        mockFetch.mockClear()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('addTrackingToEmail', () => {
        const invocation = {
            functionId: 'fn-1',
            id: 'inv-1',
            teamId: 1,
        } as any

        const extractTarget = (html: string): string => {
            const match = html.match(/href="[^"]*target=([^"&]+)/)
            if (!match) {
                throw new Error(`no tracking href in: ${html}`)
            }
            return decodeURIComponent(match[1])
        }

        it.each([
            [
                'named entity &amp;',
                '<body><a href="https://example.com/?foo=bar&amp;baz=bop">x</a></body>',
                'https://example.com/?foo=bar&baz=bop',
            ],
            [
                'decimal numeric entity &#38;',
                '<body><a href="https://example.com/?a=1&#38;b=2">x</a></body>',
                'https://example.com/?a=1&b=2',
            ],
            [
                'hex numeric entity &#x26;',
                '<body><a href="https://example.com/?a=1&#x26;b=2">x</a></body>',
                'https://example.com/?a=1&b=2',
            ],
            [
                'plain URL with no entities',
                '<body><a href="https://example.com/path">x</a></body>',
                'https://example.com/path',
            ],
        ])('decodes %s in the redirect target', (_name, html, expected) => {
            expect(extractTarget(addTrackingToEmail(html, invocation, signer))).toBe(expected)
        })

        it('skips literal javascript: hrefs', () => {
            const html = '<body><a href="javascript:alert(1)">x</a></body>'
            const out = addTrackingToEmail(html, invocation, signer)
            expect(out).toContain('href="javascript:alert(1)"')
            expect(out).not.toContain('target=')
        })

        it('skips entity-encoded javascript: hrefs after decoding', () => {
            const html = '<body><a href="java&#x73;cript:alert(1)">x</a></body>'
            const out = addTrackingToEmail(html, invocation, signer)
            expect(out).toContain('href="java&#x73;cript:alert(1)"')
            expect(out).not.toContain('target=')
        })
    })

    describe('decodeHtmlEntitiesInHref', () => {
        it.each([
            ['https://example.com/?a=1&amp;b=2', 'https://example.com/?a=1&b=2'],
            ['https://example.com/?a=1&#38;b=2', 'https://example.com/?a=1&b=2'],
            ['https://example.com/?a=1&#x26;b=2', 'https://example.com/?a=1&b=2'],
            ['https://example.com/?a=1&amp;b=2&amp;c=3', 'https://example.com/?a=1&b=2&c=3'],
            ['https://example.com/path', 'https://example.com/path'],
            // Non-entity ampersands (legacy unencoded HTML) pass through untouched.
            ['https://example.com/?a=1&b=2', 'https://example.com/?a=1&b=2'],
            // Out-of-range code points (> 0x10FFFF) must not throw RangeError;
            // the entity is left as-is.
            ['https://example.com/?x=&#x200000;', 'https://example.com/?x=&#x200000;'],
            ['https://example.com/?x=&#2097152;', 'https://example.com/?x=&#2097152;'],
        ])('decodes %s to %s', (input, expected) => {
            expect(decodeHtmlEntitiesInHref(input)).toBe(expected)
        })
    })

    describe('api', () => {
        // NOTE: These tests are done via the CdpApi router so we can get full coverage of the code
        let api: CdpApi
        let app: express.Application
        let hogFunction: HogFunctionType
        const invocationId = 'invocation-id'
        let server: Server

        beforeEach(async () => {
            api = new CdpApi(hub, createCdpConsumerDeps(hub), {
                hogQueue: createMockJobQueue(),
                hogflowQueue: createMockJobQueue(),
            })
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            hogFunction = await insertHogFunction(hub.postgres, team.id)
        })

        afterEach(() => {
            server.close()
        })

        // Metrics are tracked via SES webhooks, not the direct pixel/redirect handlers,
        // to avoid double counting. These tests verify the handlers still serve correct
        // responses without recording metrics.
        describe('handleEmailTrackingRedirect', () => {
            it('should redirect to the target url without recording metrics', async () => {
                const phId = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/redirect?ph_id=${phId}&target=https://example.com`)
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })

            it('should return 404 if the target is not provided', async () => {
                const phId = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/redirect?ph_id=${phId}`)
                expect(res.status).toBe(404)
            })
        })

        describe('email tracking pixel', () => {
            it('should return a gif image without recording metrics', async () => {
                const phId = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/pixel?ph_id=${phId}`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })

            it('should return a 200 even if the tracking code is invalid', async () => {
                const res = await supertest(app).get(`/public/m/pixel?ph_id=invalid-tracking-code`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })
    })
})
