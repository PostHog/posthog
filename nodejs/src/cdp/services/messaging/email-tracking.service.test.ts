import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFunctionType } from '~/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '~/config/kafka-topics'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'

import { Hub, Team } from '../../../types'
import { PIXEL_GIF } from './email-tracking.service'
import { generateEmailTrackingCode } from './helpers/tracking-code'

describe('EmailTrackingService', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub.postgres)

        mockFetch.mockClear()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('api', () => {
        // NOTE: These tests are done via the CdpApi router so we can get full coverage of the code
        let api: CdpApi
        let app: express.Application
        let hogFunction: HogFunctionType
        const invocationId = 'invocation-id'
        let server: Server

        beforeEach(async () => {
            api = new CdpApi(hub, createCdpConsumerDeps(hub))
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
                const phId = generateEmailTrackingCode({
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
                const phId = generateEmailTrackingCode({
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
                const phId = generateEmailTrackingCode({
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

        describe('SES webhook log entries', () => {
            it('writes a per-recipient log entry for a hog_flow delivery', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )

                const phId = generateEmailTrackingCode({
                    functionId: hogFlow.id,
                    id: invocationId,
                    teamId: team.id,
                    state: { actionId: 'act789' },
                })

                const res = await supertest(app)
                    .post('/public/m/ses_webhook')
                    .set('Content-Type', 'text/plain')
                    .send(
                        JSON.stringify([
                            {
                                eventType: 'Delivery',
                                mail: {
                                    timestamp: '2026-04-13T05:58:10Z',
                                    source: 'sender@example.com',
                                    messageId: 'msg-1',
                                    destination: ['user@example.com'],
                                    tags: { ph_id: [phId] },
                                },
                                delivery: {
                                    timestamp: '2026-04-13T05:58:10Z',
                                    smtpResponse: '250 OK',
                                    processingTimeMillis: 825,
                                    reportingMTA: 'a14-57.smtp-out.amazonses.com',
                                },
                            },
                        ])
                    )
                expect(res.status).toBe(200)

                const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                expect(logMessages).toHaveLength(1)
                expect(logMessages[0].value).toMatchObject({
                    team_id: team.id,
                    log_source: 'hog_flow',
                    log_source_id: hogFlow.id,
                    instance_id: invocationId,
                    level: 'info',
                    message: '[Action:act789] Delivered, 250 OK (825ms, reporting MTA a14-57.smtp-out.amazonses.com)',
                })
            })

            it('does not write log entries for hog_function email sends', async () => {
                const phId = generateEmailTrackingCode({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })

                const res = await supertest(app)
                    .post('/public/m/ses_webhook')
                    .set('Content-Type', 'text/plain')
                    .send(
                        JSON.stringify([
                            {
                                eventType: 'Delivery',
                                mail: {
                                    timestamp: '2026-04-13T05:58:10Z',
                                    source: 'sender@example.com',
                                    messageId: 'msg-1',
                                    destination: ['user@example.com'],
                                    tags: { ph_id: [phId] },
                                },
                                delivery: { timestamp: '2026-04-13T05:58:10Z' },
                            },
                        ])
                    )
                expect(res.status).toBe(200)

                const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                expect(logMessages).toHaveLength(0)
            })
        })
    })
})
