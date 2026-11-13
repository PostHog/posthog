import { createInMemoryJobQueue, createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch, mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import { DateTime, Settings } from 'luxon'
import supertest from 'supertest'
import express from 'ultimate-express'

import { insertHogFunction, insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFlow } from '~/cdp/schema/hogflow'
import { template as pixelTemplate } from '~/cdp/templates/_sources/pixel/pixel.template'
import { template as incomingWebhookTemplate } from '~/cdp/templates/_sources/webhook/incoming_webhook.template'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, HogFunctionType } from '~/cdp/types'
import { setupExpressApp } from '~/common/api/router'
import { defaultConfig } from '~/common/config/config'
import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { setTeamQuotaLimited } from '~/tests/helpers/quota-limits'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { getCustomHttpResponse } from '../consumers/cdp-source-webhooks.consumer'
import { createIdempotencyValkeyPool } from '../services/hogflows/idempotency-keys'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { compileHog } from '../templates/compiler'
import { compileInputs } from '../templates/test/test-helpers'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'

describe('getCustomHttpResponse', () => {
    const makeResult = (execResult: any): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> =>
        ({ execResult }) as any

    it('should return null when execResult has no httpResponse', () => {
        expect(getCustomHttpResponse(makeResult({}))).toBeNull()
        expect(getCustomHttpResponse(makeResult(null))).toBeNull()
        expect(getCustomHttpResponse(makeResult(undefined))).toBeNull()
    })

    it('should extract status and body from httpResponse', () => {
        const result = getCustomHttpResponse(makeResult({ httpResponse: { status: 200, body: 'hello' } }))
        expect(result).toEqual({
            status: 200,
            body: 'hello',
            contentType: undefined,
            isBase64Encoded: undefined,
        })
    })

    it('should default status to 500 when not a number', () => {
        const result = getCustomHttpResponse(makeResult({ httpResponse: { status: 'bad', body: 'error' } }))
        expect(result?.status).toEqual(500)
    })

    it('should extract contentType when present', () => {
        const result = getCustomHttpResponse(
            makeResult({ httpResponse: { status: 200, body: '', contentType: 'image/gif' } })
        )
        expect(result?.contentType).toEqual('image/gif')
    })

    it('should extract isBase64Encoded when present', () => {
        const result = getCustomHttpResponse(
            makeResult({
                httpResponse: {
                    status: 200,
                    body: 'R0lGODlh',
                    contentType: 'image/gif',
                    isBase64Encoded: true,
                },
            })
        )
        expect(result).toEqual({
            status: 200,
            body: 'R0lGODlh',
            contentType: 'image/gif',
            isBase64Encoded: true,
        })
    })

    it('should handle object body', () => {
        const result = getCustomHttpResponse(
            makeResult({ httpResponse: { status: 400, body: { error: 'bad request' } } })
        )
        expect(result?.body).toEqual({ error: 'bad request' })
    })
})

describe('SourceWebhooksConsumer', () => {
    // One pool for the file, because a pool for each test leaves open connections behind.
    const idempotencyValkey = createIdempotencyValkeyPool(defaultConfig)
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team

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
        let incomingWebhookTemplateId: string

        let mockExecuteSpy: jest.SpyInstance
        let mockQueueInvocationsSpy: jest.SpyInstance
        let mockQueueHogflowInvocationsSpy: jest.SpyInstance
        let hogflowQueue: ReturnType<typeof createInMemoryJobQueue>

        beforeEach(async () => {
            hub.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS = 50
            hogflowQueue = createInMemoryJobQueue()
            api = new CdpApi(
                hub,
                { ...createCdpConsumerDeps(hub), idempotencyValkey },
                {
                    hogQueue: createMockJobQueue(),
                    hogflowQueue,
                }
            )
            mockExecuteSpy = jest.spyOn(api['cdpSourceWebhooksConsumer']['hogExecutorAsync'], 'execute')
            mockQueueInvocationsSpy = jest.spyOn(api['cdpSourceWebhooksConsumer']['hogQueue'], 'queueInvocations')
            mockQueueHogflowInvocationsSpy = jest.spyOn(
                api['cdpSourceWebhooksConsumer']['hogflowQueue'],
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
            incomingWebhookTemplateId = `${incomingWebhookTemplate.id}-${team.id}`
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
        const getQueuedHogFlowIds = (): string[] => hogflowQueue.queued.map((invocation) => invocation.functionId)

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

            it('should 404 if the hog function is deleted', async () => {
                // Deletion via the django API is a soft delete that leaves `enabled` untouched
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_hogfunction SET deleted=true, updated_at = NOW() WHERE id = $1`,
                    [hogFunction.id],
                    'testKey'
                )

                const res = await doPostRequest({
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(404)
                expect(res.body).toEqual({
                    error: 'Not found',
                })
                expect(mockExecuteSpy).not.toHaveBeenCalled()
            })

            it('should capture an event using internal capture', async () => {
                // Mock the monitoring service to verify events ARE captured for regular webhooks
                const mockQueueInvocationResults = jest.spyOn(
                    api['cdpSourceWebhooksConsumer']['hogFunctionMonitoringService'],
                    'queueInvocationResults'
                )

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

                // Verify that queueInvocationResults WAS called for regular webhooks (this captures the event)
                expect(mockQueueInvocationResults).toHaveBeenCalledTimes(1)
                const result = mockQueueInvocationResults.mock.calls[0][0][0]
                expect(result.capturedPostHogEvents[0].properties).toHaveProperty('$hog_function_execution_count', 1)

                await waitForBackgroundTasks()
                expect(mockInternalFetch).toHaveBeenCalledTimes(1)
                const internalEvents = mockInternalFetch.mock.calls[0][1]

                expect(parseJSON(internalEvents.body)).toMatchObject({
                    api_key: team.api_token,
                    event: 'my-event',
                    distinct_id: 'test-distinct-id',
                    properties: {
                        $lib: 'posthog-webhook',
                        $source_url: `/project/${team.id}/functions/${hogFunction.id}`,
                        $hog_function_execution_count: 1,
                        capture_internal: true,
                    },
                })
                expect(internalEvents.headers).toEqual({ 'Content-Type': 'application/json' })
                expect(internalEvents.method).toBe('POST')
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
                    'Responded with response status - 400, reason: {"error":"\\"event\\" could not be parsed correctly"}',
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
                // Should NOT have charset=utf-8 appended (binary data, not text)
                expect(res.headers['content-type']).toEqual('image/gif')
                // Verify the response body is the exact expected GIF binary
                const expectedGif = Buffer.from('R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==', 'base64')
                expect(Buffer.from(res.body)).toEqual(expectedGif)
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
                expect(res.headers['content-type']).toEqual('image/gif')
                const expectedGif = Buffer.from('R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==', 'base64')
                expect(Buffer.from(res.body)).toEqual(expectedGif)
            })

            it('should return base64-encoded binary response with correct content-type when isBase64Encoded is true', async () => {
                const base64Png = 'iVBORw0KGgo='
                const customBinaryFunction = await insertHogFunction(hub.postgres, team.id, {
                    type: 'source_webhook',
                    hog: `return { 'httpResponse': { 'status': 200, 'body': '${base64Png}', 'contentType': 'image/png', 'isBase64Encoded': true } }`,
                    bytecode: await compileHog(
                        `return { 'httpResponse': { 'status': 200, 'body': '${base64Png}', 'contentType': 'image/png', 'isBase64Encoded': true } }`
                    ),
                    inputs: {},
                })
                const res = await doGetRequest({ webhookId: customBinaryFunction.id })
                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toEqual('image/png')
                expect(res.headers['x-content-type-options']).toEqual('nosniff')
                expect(res.headers['content-security-policy']).toEqual("default-src 'none'")
                expect(Buffer.from(res.body)).toEqual(Buffer.from(base64Png, 'base64'))
            })

            it('should return plain text string response without charset corruption when isBase64Encoded is false', async () => {
                const customTextFunction = await insertHogFunction(hub.postgres, team.id, {
                    type: 'source_webhook',
                    hog: `return { 'httpResponse': { 'status': 200, 'body': 'Hello, world!', 'contentType': 'text/plain' } }`,
                    bytecode: await compileHog(
                        `return { 'httpResponse': { 'status': 200, 'body': 'Hello, world!', 'contentType': 'text/plain' } }`
                    ),
                    inputs: {},
                })
                const res = await doGetRequest({ webhookId: customTextFunction.id })
                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toContain('text/plain')
                expect(res.headers['x-content-type-options']).toEqual('nosniff')
                expect(res.headers['content-security-policy']).toEqual("default-src 'none'")
                expect(res.text).toEqual('Hello, world!')
            })

            it.each([
                ['text/html', '<script>alert(document.cookie)</script>'],
                ['image/svg+xml', '<svg onload="alert(1)"></svg>'],
                ['application/javascript', 'alert(1)'],
                ['text/javascript', 'alert(1)'],
                ['application/xhtml+xml', '<html></html>'],
            ])(
                'should reject dangerous content type %s and fall back to text/plain',
                async (dangerousType, payload) => {
                    const fn = await insertHogFunction(hub.postgres, team.id, {
                        type: 'source_webhook',
                        hog: `return { 'httpResponse': { 'status': 200, 'body': '${payload}', 'contentType': '${dangerousType}' } }`,
                        bytecode: await compileHog(
                            `return { 'httpResponse': { 'status': 200, 'body': '${payload}', 'contentType': '${dangerousType}' } }`
                        ),
                        inputs: {},
                    })
                    const res = await doGetRequest({ webhookId: fn.id })
                    expect(res.status).toEqual(200)
                    expect(res.headers['content-type']).toContain('text/plain')
                    expect(res.headers['content-type']).not.toContain(dangerousType)
                    expect(res.headers['x-content-type-options']).toEqual('nosniff')
                    expect(res.headers['content-security-policy']).toEqual("default-src 'none'")
                    expect(res.text).toEqual(payload)
                }
            )

            it('should reject unknown content types not on the allowlist', async () => {
                const fn = await insertHogFunction(hub.postgres, team.id, {
                    type: 'source_webhook',
                    hog: `return { 'httpResponse': { 'status': 200, 'body': 'data', 'contentType': 'application/x-custom' } }`,
                    bytecode: await compileHog(
                        `return { 'httpResponse': { 'status': 200, 'body': 'data', 'contentType': 'application/x-custom' } }`
                    ),
                    inputs: {},
                })
                const res = await doGetRequest({ webhookId: fn.id })
                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toContain('text/plain')
            })

            it('should reject dangerous content type with charset parameter', async () => {
                const fn = await insertHogFunction(hub.postgres, team.id, {
                    type: 'source_webhook',
                    hog: `return { 'httpResponse': { 'status': 200, 'body': '<script>alert(1)</script>', 'contentType': 'text/html; charset=utf-8' } }`,
                    bytecode: await compileHog(
                        `return { 'httpResponse': { 'status': 200, 'body': '<script>alert(1)</script>', 'contentType': 'text/html; charset=utf-8' } }`
                    ),
                    inputs: {},
                })
                const res = await doGetRequest({ webhookId: fn.id })
                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toContain('text/plain')
                expect(res.headers['content-type']).not.toContain('text/html')
            })

            it('should strip parameters from allowlisted content types', async () => {
                const fn = await insertHogFunction(hub.postgres, team.id, {
                    type: 'source_webhook',
                    hog: `return { 'httpResponse': { 'status': 200, 'body': 'hello', 'contentType': 'text/plain; charset=utf-7' } }`,
                    bytecode: await compileHog(
                        `return { 'httpResponse': { 'status': 200, 'body': 'hello', 'contentType': 'text/plain; charset=utf-7' } }`
                    ),
                    inputs: {},
                })
                const res = await doGetRequest({ webhookId: fn.id })
                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toContain('text/plain')
                expect(res.headers['content-type']).not.toContain('utf-7')
            })

            it('should default to application/octet-stream when isBase64Encoded is true but no contentType', async () => {
                const base64Data = 'AQIDBA=='
                const customBinaryFunction = await insertHogFunction(hub.postgres, team.id, {
                    type: 'source_webhook',
                    hog: `return { 'httpResponse': { 'status': 200, 'body': '${base64Data}', 'isBase64Encoded': true } }`,
                    bytecode: await compileHog(
                        `return { 'httpResponse': { 'status': 200, 'body': '${base64Data}', 'isBase64Encoded': true } }`
                    ),
                    inputs: {},
                })
                const res = await doGetRequest({ webhookId: customBinaryFunction.id })
                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toEqual('application/octet-stream')
                expect(Buffer.from(res.body)).toEqual(Buffer.from(base64Data, 'base64'))
            })
        })

        describe('hog flow processing', () => {
            let hogFlow: HogFlow

            beforeEach(async () => {
                const template = await insertHogFunctionTemplate(hub.postgres, {
                    ...incomingWebhookTemplate,
                    id: incomingWebhookTemplateId,
                })
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
                expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(1)
                const call = mockQueueHogflowInvocationsSpy.mock.calls[0][0][0]
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
                ])
            })

            it('records a running row and stamps the run start into the queued state', async () => {
                // Lifecycle rows are gated on this flag, which is off by default outside dev.
                hub.HOG_INVOCATION_RESULTS_ENABLED = true
                let stateWhenQueued: string | undefined
                // Snapshot at call time, so a stamp applied after queueInvocations does not count.
                mockQueueHogflowInvocationsSpy.mockImplementation((invocations: any[]) => {
                    stateWhenQueued = JSON.stringify(invocations[0].state)
                    return Promise.resolve()
                })

                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })
                expect(res.status).toEqual(201)
                await waitForBackgroundTasks()

                const rows = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)
                expect(rows).toHaveLength(1)
                expect(rows[0].value).toMatchObject({
                    invocation_id: mockQueueHogflowInvocationsSpy.mock.calls[0][0][0].id,
                    team_id: team.id,
                    function_kind: 'hog_flow',
                    function_id: hogFlow.id,
                    status: 'running',
                })

                expect(parseJSON(stateWhenQueued!).firstScheduledAt).toEqual(rows[0].value.first_scheduled_at)
            })

            it('records no running row when the workflow cannot be queued', async () => {
                hub.HOG_INVOCATION_RESULTS_ENABLED = true
                mockQueueHogflowInvocationsSpy.mockRejectedValueOnce(new Error('queue unavailable'))

                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(500)
                await waitForBackgroundTasks()
                // A row here would show a run that never entered cyclotron as permanently running.
                expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)).toEqual([])
            })

            it('refuses to start a run when the team is over its workflow quota', async () => {
                const billableHogFlow = await insertHogFlow(hub.postgres, {
                    ...hogFlow,
                    id: new UUIDT().toString(),
                    billable_action_types: ['function'],
                })
                await setTeamQuotaLimited(hub, team, 'workflow_destinations_dispatched', true)

                const res = await doPostRequest({
                    webhookId: billableHogFlow.id,
                    body: { event: 'my-event', distinct_id: 'test-distinct-id' },
                })

                expect(res.status).toEqual(429)
                expect(res.body).toEqual({ error: 'The project is over its workflow quota' })
                expect(getQueuedHogFlowIds()).toEqual([])
                await waitForBackgroundTasks()
                expect(getLogs()).toContain('[Action:trigger] Started no run: The project is over its workflow quota')
                expect(getMetrics()).toContainEqual(
                    expect.objectContaining({
                        app_source_id: billableHogFlow.id,
                        metric_kind: 'failure',
                        metric_name: 'quota_limited',
                        count: 1,
                    })
                )
            })

            it.each([
                ['queues a run under the workflow quota', false, 1],
                ['queues no run over the workflow quota', true, 0],
            ])('tracking pixel workflow serves its image and %s', async (_name, overQuota, queuedRuns) => {
                const template = await insertHogFunctionTemplate(hub.postgres, {
                    ...pixelTemplate,
                    id: `${pixelTemplate.id}-${team.id}`,
                })
                const pixelHogFlow = new FixtureHogFlowBuilder()
                    .withTeamId(team.id)
                    .withSimpleWorkflow({
                        trigger: {
                            type: 'tracking_pixel',
                            template_id: template.template_id,
                            inputs: {
                                event: { value: 'my-event', bytecode: await compileHog(`return f'my-event'`) },
                                distinct_id: {
                                    value: '{request.query.ph_distinct_id}',
                                    bytecode: await compileHog(`return f'{request.query.ph_distinct_id}'`),
                                },
                            },
                        },
                    })
                    .build()
                await insertHogFlow(hub.postgres, { ...pixelHogFlow, billable_action_types: ['function'] })
                await setTeamQuotaLimited(hub, team, 'workflow_destinations_dispatched', overQuota)

                const res = await doGetRequest({ webhookId: `${pixelHogFlow.id}.gif?ph_distinct_id=test-distinct-id` })

                expect(res.status).toEqual(200)
                expect(res.headers['content-type']).toEqual('image/gif')
                expect(getQueuedHogFlowIds()).toEqual(Array(queuedRuns).fill(pixelHogFlow.id))
            })

            describe('idempotency key', () => {
                const postWithKey = (webhookId: string, idempotencyKey: string) =>
                    doPostRequest({
                        webhookId,
                        headers: { 'Idempotency-Key': idempotencyKey },
                        body: { distinct_id: 'test-distinct-id' },
                    })

                const insertSecondHogFlow = async (): Promise<HogFlow> => {
                    const other = new FixtureHogFlowBuilder()
                        .withTeamId(team.id)
                        .withSimpleWorkflow({ trigger: hogFlow.trigger })
                        .build()
                    await insertHogFlow(hub.postgres, other)
                    return other
                }

                it('queues one run and answers duplicate for a repeated key on the same workflow', async () => {
                    hub.HOG_INVOCATION_RESULTS_ENABLED = true
                    const first = await postWithKey(hogFlow.id, 'escalation-1')
                    const second = await postWithKey(hogFlow.id, 'escalation-1')

                    expect(first.status).toEqual(201)
                    expect(first.body.status).toEqual('queued')
                    expect(second.status).toEqual(200)
                    expect(second.body.status).toEqual('duplicate')
                    expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(1)

                    await waitForBackgroundTasks()
                    expect(
                        mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)
                    ).toHaveLength(1)
                    expect(getLogs()).toContainEqual(
                        expect.stringContaining('Skipped duplicate request for Idempotency-Key "escalation-1"')
                    )
                })

                it('answers duplicate for a repeated key after the team goes over its workflow quota', async () => {
                    const billableHogFlow = await insertHogFlow(hub.postgres, {
                        ...hogFlow,
                        id: new UUIDT().toString(),
                        billable_action_types: ['function'],
                    })
                    const first = await postWithKey(billableHogFlow.id, 'escalation-quota')
                    await setTeamQuotaLimited(hub, team, 'workflow_destinations_dispatched', true)
                    const second = await postWithKey(billableHogFlow.id, 'escalation-quota')

                    expect(first.status).toEqual(201)
                    expect(second.status).toEqual(200)
                    expect(second.body.status).toEqual('duplicate')
                    expect(getQueuedHogFlowIds()).toEqual([billableHogFlow.id])
                })

                it('releases a key refused over quota so a retry queues the run once under quota', async () => {
                    const billableHogFlow = await insertHogFlow(hub.postgres, {
                        ...hogFlow,
                        id: new UUIDT().toString(),
                        billable_action_types: ['function'],
                    })
                    await setTeamQuotaLimited(hub, team, 'workflow_destinations_dispatched', true)

                    const refused = await postWithKey(billableHogFlow.id, 'escalation-quota-retry')
                    await setTeamQuotaLimited(hub, team, 'workflow_destinations_dispatched', false)
                    const retried = await postWithKey(billableHogFlow.id, 'escalation-quota-retry')

                    expect(refused.status).toEqual(429)
                    expect(retried.status).toEqual(201)
                    expect(getQueuedHogFlowIds()).toEqual([billableHogFlow.id])
                })

                it('queues a run on each workflow that receives the same key', async () => {
                    const otherHogFlow = await insertSecondHogFlow()

                    const first = await postWithKey(hogFlow.id, 'escalation-2')
                    const second = await postWithKey(otherHogFlow.id, 'escalation-2')

                    expect(first.status).toEqual(201)
                    expect(second.status).toEqual(201)
                    expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(2)
                })

                it.each([
                    [
                        'queueing fails',
                        () => mockQueueHogflowInvocationsSpy.mockRejectedValueOnce(new Error('queue unavailable')),
                    ],
                    [
                        'the quota lookup fails',
                        () =>
                            jest
                                .spyOn(hub.quotaLimiting, 'isTeamQuotaLimited')
                                .mockRejectedValueOnce(new Error('team cache unavailable')),
                    ],
                ])('releases the key when %s so a retry queues the run', async (_name, failOnce) => {
                    const billableHogFlow = await insertHogFlow(hub.postgres, {
                        ...hogFlow,
                        id: new UUIDT().toString(),
                        billable_action_types: ['function'],
                    })
                    failOnce()

                    const failed = await postWithKey(billableHogFlow.id, 'escalation-3')
                    const retried = await postWithKey(billableHogFlow.id, 'escalation-3')

                    expect(failed.status).toEqual(500)
                    expect(retried.status).toEqual(201)
                    expect(retried.body.status).toEqual('queued')
                    expect(getQueuedHogFlowIds()).toEqual([billableHogFlow.id])
                })

                it('tells a retry to wait while the first request is still queueing', async () => {
                    let finishQueueing: () => void = () => {}
                    mockQueueHogflowInvocationsSpy.mockImplementationOnce(
                        () => new Promise<void>((resolve) => (finishQueueing = resolve))
                    )
                    const first = postWithKey(hogFlow.id, 'escalation-5').then((res) => res)
                    await waitForExpect(() => expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(1))

                    const retry = await postWithKey(hogFlow.id, 'escalation-5')
                    finishQueueing()

                    expect(retry.status).toEqual(409)
                    expect(retry.body.status).toEqual('in_flight')
                    expect((await first).status).toEqual(201)
                    expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(1)
                })

                it('queues the run when the idempotency store never answers, and releases it if queueing fails', async () => {
                    const valkey = api['cdpSourceWebhooksConsumer']['idempotencyKeys']['valkey']!
                    const useClient = valkey.useClient
                    let reservations = 0
                    jest.spyOn(valkey, 'useClient').mockImplementation((options, callback) => {
                        if (options.name === 'idempotency-reserve' && reservations++ === 0) {
                            void useClient(options, callback)
                            return new Promise(() => {})
                        }
                        return useClient(options, callback)
                    })
                    mockQueueHogflowInvocationsSpy.mockRejectedValueOnce(new Error('queue unavailable'))

                    const failed = await postWithKey(hogFlow.id, 'escalation-4')
                    const retried = await postWithKey(hogFlow.id, 'escalation-4')

                    expect(failed.status).toEqual(500)
                    expect(retried.status).toEqual(201)
                    expect(retried.body.status).toEqual('queued')
                    expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(2)
                })

                it('rejects a key longer than 255 characters without queueing', async () => {
                    const res = await postWithKey(hogFlow.id, 'a'.repeat(256))

                    expect(res.status).toEqual(400)
                    expect(res.body.error).toEqual('Idempotency-Key must be 255 characters or fewer')
                    expect(mockQueueHogflowInvocationsSpy).not.toHaveBeenCalled()
                })
            })

            it('does not report a workflow trigger as CDP usage', async () => {
                const reportBillableInvocation = jest.spyOn(
                    api['cdpSourceWebhooksConsumer']['cdpUsageReporter'],
                    'reportBillableInvocation'
                )

                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(201)
                await waitForBackgroundTasks()
                expect(reportBillableInvocation).not.toHaveBeenCalled()
            })

            it('does not report usage when queueing the workflow fails', async () => {
                const reportBillableInvocation = jest.spyOn(
                    api['cdpSourceWebhooksConsumer']['cdpUsageReporter'],
                    'reportBillableInvocation'
                )
                mockQueueHogflowInvocationsSpy.mockRejectedValueOnce(new Error('queue unavailable'))

                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                    },
                })

                expect(res.status).toEqual(500)
                await waitForBackgroundTasks()
                expect(reportBillableInvocation).not.toHaveBeenCalled()
                expect(getMetrics()).not.toContainEqual(
                    expect.objectContaining({
                        metric_kind: 'billing',
                        metric_name: 'billable_invocation',
                    })
                )
            })

            it('should not capture webhook event to database and should remove execution count property', async () => {
                // Mock the monitoring service to track what events would be captured
                const mockQueueInvocationResults = jest.spyOn(
                    api['cdpSourceWebhooksConsumer']['hogFunctionMonitoringService'],
                    'queueInvocationResults'
                )

                const res = await doPostRequest({
                    webhookId: hogFlow.id,
                    body: {
                        event: 'my-event',
                        distinct_id: 'test-distinct-id',
                        properties: {
                            custom_prop: 'custom_value',
                        },
                    },
                })

                expect(res.status).toEqual(201)

                // Verify that queueInvocationResults was NOT called for workflows
                // (this is what actually captures the event)
                expect(mockQueueInvocationResults).not.toHaveBeenCalled()

                // Verify the workflow invocation was queued to hogflowQueue
                expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(1)
                const invocation = mockQueueHogflowInvocationsSpy.mock.calls[0][0][0]

                expect(invocation.state.event).toMatchObject({
                    event: 'my-event',
                    distinct_id: 'test-distinct-id',
                    properties: expect.objectContaining({}),
                })

                // Explicitly check that $hog_function_execution_count is not in the properties
                // this key prevents the infinite loop protection from triggering
                expect(invocation.state.event.properties).not.toHaveProperty('$hog_function_execution_count')
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
                    '[Action:trigger] Responded with response status - 400, reason: {"error":"\\"distinct_id\\" could not be parsed correctly"}',
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
                            template_id: incomingWebhookTemplateId,
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
                    '[Action:trigger] Error triggering flow: Could not execute bytecode for input field: distinct_id: Global variable not found: i.do.not.exist',
                ])
                expect(getMetrics()).toEqual([
                    expect.objectContaining({ metric_kind: 'failure', metric_name: 'trigger_failed', count: 1 }),
                ])
            })

            describe('manual trigger', () => {
                const buildManualHogFlow = async (
                    overrides: { status?: HogFlow['status']; event?: string } = {}
                ): Promise<HogFlow> => {
                    const event = overrides.event ?? '$workflow_triggered'
                    const manualHogFlow = new FixtureHogFlowBuilder()
                        .withTeamId(team.id)
                        .withStatus(overrides.status ?? 'active')
                        .withSimpleWorkflow({
                            trigger: {
                                type: 'manual',
                                template_id: incomingWebhookTemplateId,
                                inputs: {
                                    event: { value: event, bytecode: await compileHog(`return f'${event}'`) },
                                    distinct_id: {
                                        value: '{request.body.user_id}',
                                        bytecode: await compileHog(`return f'{request.body.user_id}'`),
                                    },
                                    method: { value: 'POST', bytecode: await compileHog(`return f'POST'`) },
                                },
                            },
                        })
                        .build()
                    await insertHogFlow(hub.postgres, manualHogFlow)
                    return manualHogFlow
                }

                type ManualRunClaims = { teamId: number; hogFlowId: string; userId: string }
                const mintManualRunToken = (claims: ManualRunClaims) =>
                    new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_MANUAL_RUN, hub.WORKFLOWS_CANCEL_JWT_SECRET).mint(
                        {
                            team_id: claims.teamId,
                            hog_flow_id: claims.hogFlowId,
                            user_id: claims.userId,
                        }
                    )

                const doManualRequest = (
                    teamId: number,
                    hogFlowId: string,
                    body: Record<string, any>,
                    tokenClaims: ManualRunClaims | null = { teamId, hogFlowId, userId: body.user_id }
                ) => {
                    const request = supertest(app)
                        .post(`/api/projects/${teamId}/hog_flows/${hogFlowId}/manual_invocations`)
                        .set('Content-Type', 'application/json')
                    if (tokenClaims) {
                        request.set('Authorization', `Bearer ${mintManualRunToken(tokenClaims)}`)
                    }
                    return request.send(body)
                }

                it('queues a run for the user who started it, with their variables', async () => {
                    const manualHogFlow = await buildManualHogFlow()

                    const res = await doManualRequest(team.id, manualHogFlow.id, {
                        user_id: 'user@example.com',
                        variables: { greeting: 'Hello' },
                    })

                    expect(res.status).toEqual(200)
                    expect(res.body).toEqual({ status: 'queued', invocation_id: expect.any(String) })
                    expect(mockQueueHogflowInvocationsSpy).toHaveBeenCalledTimes(1)
                    const invocation = mockQueueHogflowInvocationsSpy.mock.calls[0][0][0]
                    expect(invocation.id).toEqual(res.body.invocation_id)
                    expect(invocation.state.event).toMatchObject({
                        event: '$workflow_triggered',
                        distinct_id: 'user@example.com',
                    })
                    expect(invocation.state.variables).toEqual({ greeting: 'Hello' })
                })

                it('refuses a run over the workflow quota with the quota reason', async () => {
                    const manualHogFlow = await buildManualHogFlow()
                    const billableHogFlow = await insertHogFlow(hub.postgres, {
                        ...manualHogFlow,
                        id: new UUIDT().toString(),
                        billable_action_types: ['function'],
                    })
                    await setTeamQuotaLimited(hub, team, 'workflow_destinations_dispatched', true)

                    const res = await doManualRequest(team.id, billableHogFlow.id, {
                        user_id: 'user@example.com',
                        variables: {},
                    })

                    expect(res.status).toEqual(422)
                    expect(res.body.error).toEqual(
                        'The trigger refused the run (429): The project is over its workflow quota'
                    )
                    expect(getQueuedHogFlowIds()).toEqual([])
                })

                type RefusalCase = {
                    teamOffset: number
                    trigger: 'manual' | 'webhook'
                    status: HogFlow['status']
                    token: 'valid' | 'none' | 'other workflow' | 'other user'
                    malformedId?: boolean
                    variables?: unknown
                }
                it.each<[string, RefusalCase, number]>([
                    ['without a token', { teamOffset: 0, trigger: 'manual', status: 'active', token: 'none' }, 401],
                    [
                        "with another workflow's token",
                        { teamOffset: 0, trigger: 'manual', status: 'active', token: 'other workflow' },
                        401,
                    ],
                    [
                        "with another user's token",
                        { teamOffset: 0, trigger: 'manual', status: 'active', token: 'other user' },
                        401,
                    ],
                    ['another team', { teamOffset: 1, trigger: 'manual', status: 'active', token: 'valid' }, 404],
                    ['a webhook trigger', { teamOffset: 0, trigger: 'webhook', status: 'active', token: 'valid' }, 400],
                    [
                        'an inactive workflow',
                        { teamOffset: 0, trigger: 'manual', status: 'draft', token: 'valid' },
                        400,
                    ],
                    [
                        'an id that is not a UUID',
                        { teamOffset: 0, trigger: 'manual', status: 'active', token: 'valid', malformedId: true },
                        400,
                    ],
                    [
                        'variables that are not an object',
                        { teamOffset: 0, trigger: 'manual', status: 'active', token: 'valid', variables: ['a'] },
                        400,
                    ],
                ])('refuses to run %s', async (_name, options, expectedStatus) => {
                    const target =
                        options.trigger === 'webhook' ? hogFlow : await buildManualHogFlow({ status: options.status })
                    const teamId = team.id + options.teamOffset
                    const hogFlowId = options.malformedId ? 'not-a-uuid' : target.id
                    const tokenClaims = {
                        valid: { teamId, hogFlowId, userId: 'user@example.com' },
                        none: null,
                        'other workflow': { teamId, hogFlowId: hogFlow.id, userId: 'user@example.com' },
                        'other user': { teamId, hogFlowId: target.id, userId: 'someone-else@example.com' },
                    }[options.token]

                    const body = {
                        user_id: 'user@example.com',
                        ...('variables' in options ? { variables: options.variables } : {}),
                    }
                    const res = await doManualRequest(teamId, hogFlowId, body, tokenClaims)

                    expect(res.status).toEqual(expectedStatus)
                    expect(mockQueueHogflowInvocationsSpy).not.toHaveBeenCalled()
                })

                it("reports the trigger's refusal instead of a success when it starts no run", async () => {
                    // A manual trigger copied from a webhook reads an event the request does not carry.
                    const manualHogFlow = await buildManualHogFlow({ event: '{request.body.event}' })

                    const res = await doManualRequest(team.id, manualHogFlow.id, { user_id: 'user@example.com' })

                    expect(res.status).toEqual(422)
                    expect(res.body.error).toContain('The trigger refused the run (400)')
                    expect(mockQueueHogflowInvocationsSpy).not.toHaveBeenCalled()
                })

                it('refuses a manual trigger on the public webhook route', async () => {
                    const manualHogFlow = await buildManualHogFlow()

                    const res = await doPostRequest({
                        webhookId: manualHogFlow.id,
                        body: { user_id: 'user@example.com' },
                    })

                    expect(res.status).toEqual(403)
                    expect(mockExecuteSpy).not.toHaveBeenCalled()
                    expect(mockQueueHogflowInvocationsSpy).not.toHaveBeenCalled()
                })
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
