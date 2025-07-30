// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import crypto from 'crypto'
import express from 'ultimate-express'

import { closeHub, createHub } from '~/utils/db/hub'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { CdpApi } from '~/cdp/cdp-api'
import supertest from 'supertest'
import { setupExpressApp } from '~/router'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { HogFunctionType } from '~/cdp/types'
import { HogFlow } from '~/schema/hogflow'
import { Server } from 'http'
import { template as incomingWebhookTemplate } from '~/cdp/templates/_sources/webhook/incoming_webhook.template'
import { compileHog } from '../templates/compiler'
import { compileInputs } from '../templates/test/test-helpers'

describe('SourceWebhooksConsumer', () => {
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
        let server: Server

        beforeEach(async () => {
            api = new CdpApi(hub)
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            hogFunction = await insertHogFunction(hub.postgres, team.id, {
                type: 'source_webhook',
                hog: incomingWebhookTemplate.code,
                bytecode: await compileHog(incomingWebhookTemplate.code),
                inputs: await compileInputs(incomingWebhookTemplate, {}),
            })
        })

        afterEach(async () => {
            server.close()
            await api.stop()
        })

        const doRequest = async (options: {
            hogFunctionId?: string
            method?: string
            headers?: Record<string, string>
            body?: Record<string, any>
        }) => {
            return supertest(app)
                .post(`/public/webhooks/${options.hogFunctionId ?? hogFunction.id}`)
                .set('Content-Type', 'application/json')
                .set(options.headers ?? {})
                .send(options.body)
        }

        describe('processWebhook', () => {
            const getLogs = (): string[] => {
                const res = mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')
                return res.map((x) => x.value.message) as string[]
            }

            it('should 404 if the hog function does not exist', async () => {
                const res = await doRequest({
                    hogFunctionId: 'non-existent-hog-function-id',
                })
                expect(res.status).toEqual(404)
                expect(res.body).toEqual({
                    error: 'Not found',
                })
            })

            it('should process a webhook', async () => {
                const res = await doRequest({
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(200)
                expect(res.body).toEqual({
                    status: 'ok',
                })
                expect(getLogs()).toEqual([])
            })

            it('should log custom errors', async () => {
                const res = await doRequest({
                    body: {
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(400)
                expect(res.body).toEqual({
                    error: '"event" cannot be empty',
                })
                expect(getLogs()).toEqual([
                    expect.stringContaining('Function completed'),
                    'Responded with response status - 400',
                ])
            })
        })
    })
})
