// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import express from 'ultimate-express'

import { closeHub, createHub } from '~/utils/db/hub'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { CdpApi } from '~/cdp/cdp-api'
import supertest from 'supertest'
import { setupExpressApp } from '~/router'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { HogFunctionType } from '~/cdp/types'
import { Server } from 'http'
import { template as incomingWebhookTemplate } from '~/cdp/templates/_sources/webhook/incoming_webhook.template'
import { compileHog } from '../templates/compiler'
import { compileInputs } from '../templates/test/test-helpers'
import { Team, Hub } from '~/types'
import { DateTime } from 'luxon'
import { forSnapshot } from '~/tests/helpers/snapshots'

describe('SourceWebhooksConsumer', () => {
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

            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        })

        afterEach(async () => {
            await api.stop()
            server.close()
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

        const waitForBackgroundTasks = async () => {
            await api['cdpSourceWebhooksConsumer']['promiseScheduler'].waitForAllSettled()
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

            it('should process a webhook and emit a capture event', async () => {
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

                await waitForBackgroundTasks()

                const events = mockProducerObserver.getProducedKafkaMessagesForTopic(
                    hub.HOG_FUNCTION_MONITORING_EVENTS_PRODUCED_TOPIC
                )

                expect(events).toHaveLength(1)

                expect(forSnapshot(events[0])).toMatchInlineSnapshot(`
                    {
                      "headers": {
                        "distinct_id": "test-distinct-id",
                        "token": "THIS IS NOT A TOKEN FOR TEAM 2",
                      },
                      "key": "THIS IS NOT A TOKEN FOR TEAM 2:test-distinct-id",
                      "topic": "events_plugin_ingestion_test",
                      "value": {
                        "data": "{"event":"my-event","distinct_id":"test-distinct-id","properties":{"$ip":"0000:0000:0000:0000:0000:ffff:7f00:0001","$lib":"posthog-webhook","$source_url":"/project/2/functions/<REPLACED-UUID-1>","$hog_function_execution_count":1},"timestamp":"2025-01-01T00:00:00.000Z"}",
                        "distinct_id": "test-distinct-id",
                        "now": "2025-01-01T01:00:00.000+01:00",
                        "sent_at": "2025-01-01T01:00:00.000+01:00",
                        "token": "THIS IS NOT A TOKEN FOR TEAM 2",
                        "uuid": "<REPLACED-UUID-0>",
                      },
                    }
                `)
            })

            it('should log custom errors', async () => {
                const res = await doRequest({
                    body: {
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(400)
                expect(res.body).toEqual({
                    error: '"event" could not be parsed correctly',
                })
                expect(getLogs()).toEqual([
                    expect.stringContaining('Function completed'),
                    'Responded with response status - 400',
                ])
            })
        })
    })
})
