import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import crypto from 'crypto'
import { Server } from 'http'
import { DateTime, Settings } from 'luxon'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { insertHogFunction, insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFunctionType } from '~/cdp/types'
import { KAFKA_WAREHOUSE_SOURCE_WEBHOOKS } from '~/config/kafka-topics'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { parseJSON } from '~/utils/json-parse'

import { compileInputs } from '../templates/test/test-helpers'

const STRIPE_TEMPLATE_ID = 'template-warehouse-source-stripe'

const STRIPE_INPUTS_SCHEMA = [
    {
        type: 'string' as const,
        key: 'signing_secret',
        label: 'Signing secret',
        required: false,
        secret: true,
        hidden: false,
        description: 'Used to validate the webhook came from Stripe',
    },
    {
        type: 'boolean' as const,
        key: 'bypass_signature_check',
        label: 'Bypass signature check',
        description: 'If set, the stripe-signature header will not be checked. This is not recommended.',
        default: false,
        required: false,
        secret: false,
    },
]

const STRIPE_HOG_CODE = `
if(request.method != 'POST') {
  return {
    'httpResponse': {
      'status': 405,
      'body': 'Method not allowed'
    }
  }
}

if (not inputs.bypass_signature_check) {
  let body := request.stringBody
  let signatureHeader := request.headers['stripe-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let headerParts := splitByString(',', signatureHeader)
  let timestamp := null
  let v1Signature := null

  for (let _, part in headerParts) {
      let trimmed := trim(part)
      if (trimmed like 't=%') {
          let tParts := splitByString('=', trimmed, 2)
          if (length(tParts) = 2) {
              timestamp := tParts[2]
          }
      }
      if (trimmed like 'v1=%') {
          let v1Parts := splitByString('=', trimmed, 2)
          if (length(v1Parts) = 2) {
              v1Signature := v1Parts[2]
          }
      }
  }

  if (empty(timestamp) or empty(v1Signature)) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Could not parse signature',
        }
      }
  }

  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])

  if (computedSignature != v1Signature) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }
}

return request.body
`

// Minimal template-like object for compileInputs (only needs inputs_schema)
const stripeTemplateForInputs = { inputs_schema: STRIPE_INPUTS_SCHEMA } as any

describe('DWH source webhooks', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub)
        mockFetch.mockClear()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('handleWarehouseSourceWebhook', () => {
        let api: CdpApi
        let app: express.Application
        let server: Server
        let hogFunction: HogFunctionType

        const schemaId = 'test-schema-id-123'
        const signingSecret = 'whsec_testsecret'

        beforeEach(async () => {
            api = new CdpApi(hub, hub)
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            Settings.defaultZone = 'UTC'
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

            // Insert the warehouse source templates into the DB
            await insertHogFunctionTemplate(hub.postgres, {
                id: STRIPE_TEMPLATE_ID,
                name: 'Stripe warehouse source webhook',
                type: 'warehouse_source_webhook',
                code: STRIPE_HOG_CODE,
                inputs_schema: STRIPE_INPUTS_SCHEMA,
            })

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-warehouse-source-default',
                name: 'Default warehouse source webhook',
                type: 'warehouse_source_webhook',
                code: 'return request.body',
                inputs_schema: [],
            })

            hogFunction = await insertHogFunction(hub.postgres, team.id, {
                type: 'warehouse_source_webhook',
                template_id: STRIPE_TEMPLATE_ID,
                bytecode: [],
                inputs: {
                    ...(await compileInputs(stripeTemplateForInputs, {
                        signing_secret: signingSecret,
                        bypass_signature_check: false,
                    })),
                    schema_id: { value: schemaId },
                    source_type: { value: 'Stripe' },
                },
            })

            await api.start()
        })

        afterEach(async () => {
            await api.stop()
            server.close()
        })

        const createStripeWebhookRequest = (secret: string, body?: Record<string, any>) => {
            const payload = JSON.stringify(
                body ?? { type: 'invoice.payment_succeeded', data: { object: { id: 'inv_1' } } }
            )
            const timestamp = Math.floor(Date.now() / 1000)
            const signature = crypto
                .createHmac('sha256', secret)
                .update(`${timestamp}.${payload}`, 'utf8')
                .digest('hex')
            return {
                body: parseJSON(payload),
                headers: { 'stripe-signature': `t=${timestamp},v1=${signature}` },
            }
        }

        const doDwhPostRequest = async (options: {
            webhookId?: string
            headers?: Record<string, string>
            body?: Record<string, any>
        }) => {
            return supertest(app)
                .post(`/public/webhooks/dwh/${options.webhookId ?? hogFunction.id}`)
                .set('Content-Type', 'application/json')
                .set(options.headers ?? {})
                .send(options.body)
        }

        const getDwhKafkaMessages = () => {
            return mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_WAREHOUSE_SOURCE_WEBHOOKS)
        }

        const waitForBackgroundTasks = async () => {
            await api['cdpSourceWebhooksConsumer']['promiseScheduler'].waitForAllSettled()
        }

        it('should return 404 for non-existent webhook ID', async () => {
            const res = await doDwhPostRequest({ webhookId: 'non-existent-id' })
            expect(res.status).toEqual(404)
            expect(res.body).toEqual({ error: 'Not found' })
        })

        it('should process a valid Stripe webhook and produce to Kafka', async () => {
            const webhookReq = createStripeWebhookRequest(signingSecret)

            const res = await doDwhPostRequest({
                headers: webhookReq.headers,
                body: webhookReq.body,
            })

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ status: 'ok' })

            await waitForBackgroundTasks()

            const kafkaMessages = getDwhKafkaMessages()
            expect(kafkaMessages).toHaveLength(1)
            expect(kafkaMessages[0].key).toEqual(`${team.id}:${schemaId}`)
            expect(kafkaMessages[0].value).toMatchObject({
                type: 'invoice.payment_succeeded',
                data: { object: { id: 'inv_1' } },
            })
        })

        it('should return 400 for invalid Stripe signature', async () => {
            const webhookReq = createStripeWebhookRequest('wrong-secret')

            const res = await doDwhPostRequest({
                headers: webhookReq.headers,
                body: webhookReq.body,
            })

            expect(res.status).toEqual(400)
            expect(res.text).toEqual('Bad signature')
            expect(getDwhKafkaMessages()).toHaveLength(0)
        })

        it('should return 400 when stripe-signature header is missing', async () => {
            const res = await doDwhPostRequest({
                body: { type: 'invoice.created' },
            })

            expect(res.status).toEqual(400)
            expect(res.text).toEqual('Missing signature')
            expect(getDwhKafkaMessages()).toHaveLength(0)
        })

        it('should bypass signature check when configured', async () => {
            const bypassFunction = await insertHogFunction(hub.postgres, team.id, {
                type: 'warehouse_source_webhook',
                template_id: STRIPE_TEMPLATE_ID,
                bytecode: [],
                inputs: {
                    ...(await compileInputs(stripeTemplateForInputs, {
                        signing_secret: '',
                        bypass_signature_check: true,
                    })),
                    schema_id: { value: schemaId },
                    source_type: { value: 'Stripe' },
                },
            })

            const res = await doDwhPostRequest({
                webhookId: bypassFunction.id,
                body: { type: 'charge.succeeded', data: { object: { id: 'ch_1' } } },
            })

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ status: 'ok' })

            await waitForBackgroundTasks()

            const kafkaMessages = getDwhKafkaMessages()
            expect(kafkaMessages).toHaveLength(1)
            expect(kafkaMessages[0].key).toEqual(`${team.id}:${schemaId}`)
        })

        it('should return 500 when schema_id is missing from hog function inputs', async () => {
            const noSchemaFunction = await insertHogFunction(hub.postgres, team.id, {
                type: 'warehouse_source_webhook',
                template_id: STRIPE_TEMPLATE_ID,
                bytecode: [],
                inputs: {
                    ...(await compileInputs(stripeTemplateForInputs, {
                        signing_secret: '',
                        bypass_signature_check: true,
                    })),
                    source_type: { value: 'Stripe' },
                },
            })

            const res = await doDwhPostRequest({
                webhookId: noSchemaFunction.id,
                body: { type: 'charge.succeeded' },
            })

            expect(res.status).toEqual(500)
            expect(res.body).toEqual({ error: 'Missing schema_id on hog function' })
        })

        it('should include the full webhook body in the Kafka payload', async () => {
            const eventBody = {
                type: 'customer.subscription.created',
                data: {
                    object: {
                        id: 'sub_123',
                        customer: 'cus_456',
                        status: 'active',
                        items: { data: [{ price: { id: 'price_789' } }] },
                    },
                },
            }
            const webhookReq = createStripeWebhookRequest(signingSecret, eventBody)

            const res = await doDwhPostRequest({
                headers: webhookReq.headers,
                body: webhookReq.body,
            })

            expect(res.status).toEqual(200)
            await waitForBackgroundTasks()

            const kafkaMessages = getDwhKafkaMessages()
            expect(kafkaMessages).toHaveLength(1)
            expect(kafkaMessages[0].value).toMatchObject(eventBody)
        })
    })
})
