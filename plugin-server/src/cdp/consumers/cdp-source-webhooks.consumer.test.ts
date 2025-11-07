import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch, mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import { DateTime, Settings } from 'luxon'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { insertHogFunction, insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { CdpApi } from '~/cdp/cdp-api'
import { template as pixelTemplate } from '~/cdp/templates/_sources/pixel/pixel.template'
import { template as incomingWebhookTemplate } from '~/cdp/templates/_sources/webhook/incoming_webhook.template'
import { HogFunctionType } from '~/cdp/types'
import { HogFlow } from '~/schema/hogflow'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { compileHog } from '../templates/compiler'
import { compileInputs } from '../templates/test/test-helpers'

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
        let hogFunctionPixel: HogFunctionType
        let server: Server

        let mockExecuteSpy: jest.SpyInstance
        let mockQueueInvocationsSpy: jest.SpyInstance

        beforeEach(async () => {
            hub.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS = 50
            api = new CdpApi(hub)
            mockExecuteSpy = jest.spyOn(api['cdpSourceWebhooksConsumer']['hogExecutor'], 'execute')
            mockQueueInvocationsSpy = jest.spyOn(
                api['cdpSourceWebhooksConsumer']['cyclotronJobQueue'],
                'queueInvocations'
            )
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            hogFunction = await insertHogFunction(hub.postgres, team.id, {
                type: 'source_webhook',
                hog: incomingWebhookTemplate.code,
                bytecode: await compileHog(incomingWebhookTemplate.code),
                inputs: await compileInputs(incomingWebhookTemplate, {}),
            })

            hogFunctionPixel = await insertHogFunction(hub.postgres, team.id, {
                type: 'source_webhook',
                hog: pixelTemplate.code,
                bytecode: await compileHog(pixelTemplate.code),
                inputs: await compileInputs(pixelTemplate, {}),
            })

            Settings.defaultZone = 'UTC'

            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

            await api.start()
        })

        afterEach(async () => {
            await api.stop()
            server.close()
        })

        const doPostRequest = async (options: {
            webhookId?: string
            headers?: Record<string, string>
            body?: Record<string, any>
        }) => {
            return supertest(app)
                .post(`/public/webhooks/${options.webhookId ?? hogFunction.id}`)
                .set('Content-Type', 'application/json')
                .set(options.headers ?? {})
                .send(options.body)
        }

        const doGetRequest = async (options: {
            webhookId: string
            headers?: Record<string, string>
            body?: Record<string, any>
        }) => {
            return supertest(app)
                .get(`/public/webhooks/${options.webhookId}`)
                .set(options.headers ?? {})
                .send()
        }

        const waitForBackgroundTasks = async () => {
            await api['cdpSourceWebhooksConsumer']['promiseScheduler'].waitForAllSettled()
        }
        const getLogs = (): string[] => {
            const res = mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')
            return res.map((x) => x.value.message) as string[]
        }
        const getMetrics = (): any[] => {
            const res = mockProducerObserver.getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
            return res.map((x) => x.value) as any[]
        }

        describe('hog function processing', () => {
            it('should 404 if the hog function does not exist', async () => {
                const res = await doPostRequest({
                    webhookId: 'non-existent-hog-function-id',
                })
                expect(res.status).toEqual(404)
                expect(res.body).toEqual({
                    error: 'Not found',
                })
            })

            it('should capture an event using internal capture', async () => {
                const res = await doPostRequest({
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
                expect(mockInternalFetch).toHaveBeenCalledTimes(1)
                const internalEvents = mockInternalFetch.mock.calls[0][1]

                expect(forSnapshot(internalEvents)).toEqual({
                    body: `{"api_key":"THIS IS NOT A TOKEN FOR TEAM 2","timestamp":"2025-01-01T00:00:00.000Z","distinct_id":"test-distinct-id","sent_at":"2025-01-01T00:00:00.000Z","event":"my-event","properties":{"$ip":"0000:0000:0000:0000:0000:ffff:7f00:0001","$lib":"posthog-webhook","$source_url":"/project/2/functions/<REPLACED-UUID-0>","$hog_function_execution_count":1,"capture_internal":true}}`,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    method: 'POST',
                })
            })

            it('should log custom errors', async () => {
                const res = await doPostRequest({
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

            it('should not receive sensitive headers', async () => {
                await doPostRequest({
                    headers: {
                        'x-forwarded-for': '127.0.0.1',
                        cookie: 'test=test',
                    },
                })

                const call = mockExecuteSpy.mock.calls[0][0]
                expect(call.state.globals.request.headers).toEqual({
                    'accept-encoding': 'gzip, deflate',
                    connection: 'close',
                    'content-length': '0',
                    'content-type': 'application/json',
                    host: expect.any(String),
                })
            })

            it('should capture an event using GET request with the pixel template', async () => {
                const res = await doGetRequest({
                    webhookId: hogFunctionPixel.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(200)
                expect(res.body).toBeInstanceOf(Buffer)
                expect(res.headers['content-type']).toEqual('image/gif; charset=utf-8')
                // parse body
                const body = Buffer.from(res.body).toString()
                expect(body).toContain('GIF')
            })

            it('should allow capturing an event using GET request with gif extension', async () => {
                const res = await doGetRequest({
                    webhookId: hogFunctionPixel.id + '.gif',
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(200)
                expect(res.body).toBeInstanceOf(Buffer)
                expect(res.headers['content-type']).toEqual('image/gif; charset=utf-8')
                // parse body
                const body = Buffer.from(res.body).toString()
                expect(body).toContain('GIF')
            })
        })

        describe('hog flow processing', () => {
            let hogFlow: HogFlow

            beforeEach(async () => {
                const template = await insertHogFunctionTemplate(hub.postgres, incomingWebhookTemplate)
                hogFlow = new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'webhook',
                            template_id: template.template_id,
                            inputs: {
                                event: {
                                    value: 'my-event',
                                    bytecode: await compileHog(`return f'my-event'`),
                                },
                                distinct_id: {
                                    value: '{request.body.distinct_id}',
                                    bytecode: await compileHog(`return f'{request.body.distinct_id}'`),
                                },
                                method: {
                                    value: 'POST',
                                    bytecode: await compileHog(`return f'POST'`),
                                },
                            },
                        },
                    })
                    .build()
                await insertHogFlow(hub.postgres, hogFlow)
            })

            it('should schedule workflow run for $scheduled_at', async () => {
                const scheduledAt = '2025-01-02T12:00:00.000Z'
                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                        $scheduled_at: scheduledAt,
                    },
                })
                expect(res.status).toEqual(201)
                expect(res.body).toEqual({ status: 'queued' })
                expect(mockQueueInvocationsSpy).toHaveBeenCalledTimes(1)
                const call = mockQueueInvocationsSpy.mock.calls[0][0][0]
                expect(call.queueScheduledAt.toISO()).toEqual(scheduledAt)
                await waitForBackgroundTasks()
                expect(getLogs()).toEqual([
                    expect.stringContaining(`[Action:trigger] Workflow run scheduled for ${scheduledAt}`),
                ])
            })

            it('should 404 if the hog flow does not exist', async () => {
                const res = await doPostRequest({
                    webhookId: 'non-existent-hog-flow-id',
                })
                expect(res.status).toEqual(404)
            })

            it('should invoke a workflow with the parsed inputs', async () => {
                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(201)
                expect(res.body).toEqual({
                    status: 'queued',
                })
                expect(mockExecuteSpy).toHaveBeenCalledTimes(1)
                expect(mockQueueInvocationsSpy).toHaveBeenCalledTimes(1)
                const call = mockQueueInvocationsSpy.mock.calls[0][0][0]
                expect(call.queue).toEqual('hogflow')
                expect(call.hogFlow).toMatchObject(hogFlow)
            })

            it('should add logs and metrics', async () => {
                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(201)
                await waitForBackgroundTasks()
                expect(getLogs()).toEqual([expect.stringContaining('[Action:trigger] Function completed in')])
                expect(getMetrics()).toEqual([
                    expect.objectContaining({
                        metric_kind: 'other',
                        metric_name: 'triggered',
                        count: 1,
                    }),
                    expect.objectContaining({
                        metric_kind: 'billing',
                        metric_name: 'billable_invocation',
                        count: 1,
                    }),
                ])
            })

            it('should add logs and metrics for a controlled failed hog flow', async () => {
                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        missing_distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(400)
                expect(res.body).toEqual({
                    error: '"distinct_id" could not be parsed correctly',
                })
                await waitForBackgroundTasks()
                expect(getLogs()).toEqual([
                    expect.stringContaining('[Action:trigger] Function completed in'),
                    '[Action:trigger] Responded with response status - 400',
                ])
                expect(getMetrics()).toEqual([
                    expect.objectContaining({ metric_kind: 'failure', metric_name: 'trigger_failed', count: 1 }),
                ])
            })

            it('should add logs and metrics for an uncontrolled failed hog flow', async () => {
                // Hacky but otherwise its quite hard to trigger an uncontrolled error
                hogFlow = new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'webhook',
                            template_id: incomingWebhookTemplate.id,
                            inputs: {
                                distinct_id: {
                                    value: '{i.do.not.exist}',
                                    bytecode: await compileHog(`return f'{i.do.not.exist}'`),
                                },
                            },
                        },
                    })
                    .build()
                await insertHogFlow(hub.postgres, hogFlow)

                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        missing_distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(500)
                expect(res.body).toEqual({
                    status: 'Unhandled error',
                })
                await waitForBackgroundTasks()
                expect(getLogs()).toEqual([
                    '[Action:trigger] Error triggering flow: Could not execute bytecode for input field: distinct_id',
                ])
                expect(getMetrics()).toEqual([
                    expect.objectContaining({ metric_kind: 'failure', metric_name: 'trigger_failed', count: 1 }),
                ])
            })
        })

        describe('hogwatcher', () => {
            it('should return a degraded response if the function is degraded', async () => {
                await api['cdpSourceWebhooksConsumer']['hogWatcher'].forceStateChange(
                    hogFunction,
                    HogWatcherState.degraded
                )
                const res = await doPostRequest({
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.body).toMatchInlineSnapshot(`{}`)
                expect(mockExecuteSpy).not.toHaveBeenCalled()
                expect(mockQueueInvocationsSpy).toHaveBeenCalledTimes(1)
                const call = mockQueueInvocationsSpy.mock.calls[0][0][0]
                expect(call.queue).toEqual('hogoverflow')
            })

            it('should return a disabled response if the function is disabled', async () => {
                await api['cdpSourceWebhooksConsumer']['hogWatcher'].forceStateChange(
                    hogFunction,
                    HogWatcherState.disabled
                )
                const res = await doPostRequest({})
                expect(res.status).toEqual(429)
                expect(res.body).toEqual({
                    error: 'Disabled',
                })
                expect(mockExecuteSpy).not.toHaveBeenCalled()
                expect(mockQueueInvocationsSpy).not.toHaveBeenCalled()
            })
        })
    })
})
