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
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { HogFlow } from '~/schema/hogflow'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'

import { Hub, Team } from '../../../types'
import { PIXEL_GIF } from './email-tracking.service'
import { generateEmailTrackingCode } from './helpers/tracking-code'
import { MailjetEventBase, MailjetWebhookEvent } from './types'

describe('EmailTrackingService', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            MAILJET_SECRET_KEY: 'mailjet-secret-key',
            MAILJET_PUBLIC_KEY: 'mailjet-public-key',
        })
        team = await getFirstTeam(hub)

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
        let hogFlow: HogFlow
        const invocationId = 'invocation-id'
        let server: Server
        let exampleEvent: MailjetWebhookEvent

        beforeEach(async () => {
            api = new CdpApi(hub)
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            hogFunction = await insertHogFunction(hub.postgres, team.id)
            hogFlow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
            exampleEvent = {
                event: 'sent',
                time: Date.now(),
                email: 'test@example.com',
                mj_campaign_id: 1,
                mj_contact_id: 1,
                mj_message_id: 'test-message-id',
                smtp_reply: 'test-smtp-reply',
                MessageID: 1,
                Message_GUID: 'test-message-guid',
                customcampaign: 'test-custom-campaign',
                CustomID: '',
                Payload: generateEmailTrackingCode({ functionId: hogFunction.id, id: invocationId }),
            }
        })

        afterEach(() => {
            server.close()
        })

        describe('mailjet webhook', () => {
            const sendValidEvent = async (mailjetEvent: MailjetEventBase): Promise<supertest.Response> => {
                const payload = JSON.stringify(mailjetEvent)

                const res = await supertest(app)
                    .post(`/public/m/mailjet_webhook`)
                    .set({
                        'content-type': 'application/json',
                    })
                    .send(payload)

                return res
            }

            describe('validation', () => {
                it('should return 403 if body is missing', async () => {
                    const res = await supertest(app).post(`/public/m/mailjet_webhook`).send()

                    expect(res.status).toBe(403)
                    expect(res.body).toEqual({
                        message: 'Missing request body',
                    })
                })
            })

            it('should not track a metric if the hog function or flow is not found', async () => {
                const mailjetEvent: MailjetEventBase = {
                    ...exampleEvent,
                    Payload: 'ph_fn_id=invalid-function-id&ph_inv_id=invalid-invocation-id',
                }
                const res = await sendValidEvent(mailjetEvent)

                expect(res.status).toBe(200)
                expect(res.body).toEqual({ message: 'OK' })
                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })

            it('should track a hog flow if given', async () => {
                const mailjetEvent: MailjetEventBase = {
                    ...exampleEvent,
                    Payload: generateEmailTrackingCode({ functionId: hogFlow.id, id: invocationId }),
                }
                const res = await sendValidEvent(mailjetEvent)

                expect(res.status).toBe(200)
                expect(res.body).toEqual({ message: 'OK' })
                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(1)
                expect(messages[0].value).toMatchObject({
                    app_source: 'hog_flow',
                    app_source_id: hogFlow.id,
                    count: 1,
                    instance_id: invocationId,
                    metric_kind: 'email',
                    metric_name: 'email_sent',
                    team_id: team.id,
                })
            })

            it.each([
                ['open', 'email_opened'],
                ['click', 'email_link_clicked'],
                ['bounce', 'email_bounced'],
                ['spam', 'email_spam'],
                ['unsub', 'email_unsubscribed'],
            ] as const)('should handle valid %s event', async (event, metric) => {
                const mailjetEvent: MailjetEventBase = {
                    ...exampleEvent,
                    event,
                }
                const res = await sendValidEvent(mailjetEvent)

                expect(res.status).toBe(200)
                expect(res.body).toEqual({ message: 'OK' })
                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(1)

                expect(messages[0].value).toMatchObject({
                    app_source: 'hog_function',
                    app_source_id: hogFunction.id,
                    count: 1,
                    instance_id: invocationId,
                    metric_kind: 'email',
                    metric_name: metric,
                    team_id: team.id,
                })
            })
        })

        describe('handleEmailTrackingRedirect', () => {
            it('should redirect to the target url and track the click metric', async () => {
                const res = await supertest(app).get(
                    `/public/m/redirect?ph_fn_id=${hogFunction.id}&ph_inv_id=${invocationId}&target=https://example.com`
                )
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(1)
                expect(messages[0].value).toMatchObject({
                    app_source: 'hog_function',
                    app_source_id: hogFunction.id,
                    instance_id: invocationId,
                    metric_kind: 'email',
                    metric_name: 'email_link_clicked',
                    team_id: team.id,
                    count: 1,
                })
            })

            it('should return 404 if the target is not provided', async () => {
                const res = await supertest(app).get(
                    `/public/m/redirect?ph_fn_id=${hogFunction.id}&ph_inv_id=${invocationId}`
                )
                expect(res.status).toBe(404)
            })

            it('should redirect even if the tracking code is invalid', async () => {
                const res = await supertest(app).get(
                    `/public/m/redirect?ph_fn_id=invalid-function-id&ph_inv_id=invalid-invocation-id&target=https://example.com`
                )
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })

        describe('email tracking pixel', () => {
            it('should return a 200 and a gif image, tracking the open metric', async () => {
                const res = await supertest(app).get(
                    `/public/m/pixel?ph_fn_id=${hogFunction.id}&ph_inv_id=${invocationId}`
                )
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(1)
                expect(messages[0].value).toMatchObject({
                    app_source: 'hog_function',
                    app_source_id: hogFunction.id,
                    instance_id: invocationId,
                    metric_kind: 'email',
                    metric_name: 'email_opened',
                    team_id: team.id,
                    count: 1,
                })
            })

            it('should return a 200 even if the tracking code is invalid', async () => {
                const res = await supertest(app).get(`/public/m/pixel?ph_fn_id=${new UUIDT()}&ph_inv_id=${new UUIDT()}`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })
    })
})
