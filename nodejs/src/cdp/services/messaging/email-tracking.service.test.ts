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
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'

import { Hub, Team } from '../../../types'
import {
    addTrackingToEmail,
    decodeHtmlEntitiesInHref,
    METRIC_NAME_TO_EVENT_NAME,
    PIXEL_GIF,
    resolveEmailEngagementDistinctId,
} from './email-tracking.service'
import { generateEmailTrackingCode } from './helpers/tracking-code'

describe('EmailTrackingService', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub.postgres)

        mockFetch.mockClear()
        mockProducerObserver.resetKafkaProducer()
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
            expect(extractTarget(addTrackingToEmail(html, invocation))).toBe(expected)
        })

        it('skips literal javascript: hrefs', () => {
            const html = '<body><a href="javascript:alert(1)">x</a></body>'
            const out = addTrackingToEmail(html, invocation)
            expect(out).toContain('href="javascript:alert(1)"')
            expect(out).not.toContain('target=')
        })

        it('skips entity-encoded javascript: hrefs after decoding', () => {
            const html = '<body><a href="java&#x73;cript:alert(1)">x</a></body>'
            const out = addTrackingToEmail(html, invocation)
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

        // In production, opens/clicks come from SES webhooks. In dev/test (which jest runs as)
        // there is no SES, so the pixel/redirect handlers themselves emit the metric — these
        // tests run in test env and exercise that path.
        describe('handleEmailTrackingRedirect', () => {
            it('should redirect to the target url and record an email_link_clicked metric', async () => {
                const phId = generateEmailTrackingCode({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/redirect?ph_id=${phId}&target=https://example.com`)
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                await waitForExpect(() => {
                    const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    expect(messages).toHaveLength(1)
                    expect(messages[0].value).toMatchObject({
                        team_id: team.id,
                        metric_name: 'email_link_clicked',
                        metric_kind: 'email',
                    })
                })
            })

            it('should return 404 if the target is not provided', async () => {
                const phId = generateEmailTrackingCode({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/redirect?ph_id=${phId}`)
                expect(res.status).toBe(404)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })

        describe('email tracking pixel', () => {
            it('should return a gif image and record an email_opened metric', async () => {
                const phId = generateEmailTrackingCode({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/pixel?ph_id=${phId}`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                await waitForExpect(() => {
                    const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    expect(messages).toHaveLength(1)
                    expect(messages[0].value).toMatchObject({
                        team_id: team.id,
                        metric_name: 'email_opened',
                        metric_kind: 'email',
                    })
                })
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

    describe('resolveEmailEngagementDistinctId', () => {
        const buildInvocation = (
            globals: Partial<NonNullable<CyclotronJobInvocationHogFunction['state']['globals']>>
        ): CyclotronJobInvocationHogFunction =>
            ({
                state: { globals: globals as any },
            }) as CyclotronJobInvocationHogFunction

        it('uses event.distinct_id when present (event-triggered flow)', () => {
            const invocation = buildInvocation({
                event: { distinct_id: 'user-from-event' } as any,
                person: { id: 'person-uuid' } as any,
            })
            expect(resolveEmailEngagementDistinctId(invocation)).toBe('user-from-event')
        })

        it('falls back to person.id when event.distinct_id is empty (batch / scheduled flow)', () => {
            const invocation = buildInvocation({
                event: { distinct_id: '' } as any,
                person: { id: 'person-uuid' } as any,
            })
            expect(resolveEmailEngagementDistinctId(invocation)).toBe('person-uuid')
        })

        it('returns undefined when neither event.distinct_id nor person.id is set', () => {
            const invocation = buildInvocation({ event: { distinct_id: '' } as any })
            expect(resolveEmailEngagementDistinctId(invocation)).toBeUndefined()
        })
    })

    describe('METRIC_NAME_TO_EVENT_NAME allowlist', () => {
        it('maps every email metric we want to surface and excludes internal ones', () => {
            // Adding entries here changes the set of events customers can build insights on top of —
            // treat as a public-API change. Removing entries leaves customers with broken insights.
            expect(METRIC_NAME_TO_EVENT_NAME).toEqual({
                email_sent: '$workflows_email_sent',
                email_failed: '$workflows_email_failed',
                email_delivered: '$workflows_email_delivered',
                email_opened: '$workflows_email_opened',
                email_link_clicked: '$workflows_email_link_clicked',
                email_bounced: '$workflows_email_bounced',
                email_blocked: '$workflows_email_blocked',
            })
        })
    })
})
