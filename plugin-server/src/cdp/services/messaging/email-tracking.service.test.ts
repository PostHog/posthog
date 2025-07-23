// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import crypto from 'crypto'
import express from 'express'

import { closeHub, createHub } from '~/utils/db/hub'

import { Hub, Team } from '../../../types'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { CdpApi } from '~/cdp/cdp-api'
import supertest from 'supertest'
import { setupExpressApp } from '~/router'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { generateMailjetCustomId } from './email-tracking.service'
import { MailjetEventBase, MailjetWebhookEvent } from './types'
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { HogFunctionType } from '~/cdp/types'
import { HogFlow } from '~/schema/hogflow'

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

    describe('handleWebhook', () => {
        // NOTE: These tests are done via the CdpApi router so we can get full coverage of the code
        let api: CdpApi
        let app: express.Application
        let hogFunction: HogFunctionType
        let hogFlow: HogFlow
        const invocationId = 'invocation-id'

        let exampleEvent: MailjetWebhookEvent

        beforeEach(async () => {
            api = new CdpApi(hub)
            app = setupExpressApp()
            app.use('/', api.router())

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
                CustomID: generateMailjetCustomId({ functionId: hogFunction.id, id: invocationId }),
                Payload: JSON.stringify({}),
            }
        })

        const sendValidEvent = async (mailjetEvent: MailjetEventBase): Promise<supertest.Response> => {
            const timestamp = Date.now().toString()
            const payload = JSON.stringify(mailjetEvent)
            const signature = crypto
                .createHmac('sha256', hub.MAILJET_SECRET_KEY)
                .update(`${timestamp}.${payload}`)
                .digest('hex')

            const res = await supertest(app)
                .post(`/public/messaging/mailjet_webhook`)
                .set({
                    'x-mailjet-signature': signature,
                    'x-mailjet-timestamp': timestamp,
                    'content-type': 'application/json',
                })
                .send(payload)

            return res
        }

        describe('validation', () => {
            it('should return 403 if required headers are missing', async () => {
                const res = await supertest(app).post(`/public/messaging/mailjet_webhook`).send({})

                expect(res.status).toBe(403)
                expect(res.body).toMatchInlineSnapshot(`
                {
                  "message": "Missing required headers or body",
                }
            `)
            })

            it('should return 403 if signature is invalid', async () => {
                const timestamp = Date.now().toString()
                const res = await supertest(app)
                    .post(`/public/messaging/mailjet_webhook`)
                    .set({
                        'x-mailjet-signature': 'invalid-signature',
                        'x-mailjet-timestamp': timestamp,
                    })
                    .send(exampleEvent)

                expect(res.status).toBe(403)
                expect(res.body).toMatchInlineSnapshot(`
                {
                  "message": "Invalid signature",
                }
            `)
            })
        })

        it('should not track a metric if the hog function or flow is not found', async () => {
            const mailjetEvent: MailjetEventBase = {
                ...exampleEvent,
                CustomID: 'ph_fn_id=invalid-function-id&ph_inv_id=invalid-invocation-id',
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
                CustomID: generateMailjetCustomId({ functionId: hogFlow.id, id: invocationId }),
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
            ['click', 'email_clicked'],
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
})
