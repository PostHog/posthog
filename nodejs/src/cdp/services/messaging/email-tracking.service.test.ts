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
import { METRIC_NAME_TO_EVENT_NAME, PIXEL_GIF, resolveEmailEngagementDistinctId } from './email-tracking.service'
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
