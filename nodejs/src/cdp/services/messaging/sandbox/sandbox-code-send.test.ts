import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { ClickHouseClient } from '@clickhouse/client'
import { Server } from 'http'
import jwt from 'jsonwebtoken'
import { DateTime } from 'luxon'
import supertest from 'supertest'
import express from 'ultimate-express'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { HogFlow } from '~/cdp/schema/hogflow'
import { setupExpressApp } from '~/common/api/router'
import { KAFKA_EMAIL_STATUS, KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { FixtureHogFlowBuilder } from '../../../_tests/builders/hogflow.builder'
import { createHogFlowInvocationContext, insertHogFlow } from '../../../_tests/fixtures-hogflows'
import { CdpApi } from '../../../cdp-api'
import { createCdpCoreServices } from '../../../cdp-services'
import { CdpCyclotronWorkerEmailSandbox } from '../../../consumers/cdp-cyclotron-worker-email-sandbox.consumer'
import { CdpCyclotronWorkerEmail } from '../../../consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from '../../../consumers/cdp-cyclotron-worker-hogflow.consumer'
import { RerunJobQueues, RerunPaginatorService } from '../../../rerun/rerun-paginator.service'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationResult,
    HogFlowInvocationContext,
    MinimalAppMetric,
} from '../../../types'
import { createIdempotencyValkeyPool } from '../../hogflows/idempotency-keys'
import { SES_REJECTED, SES_THROTTLE } from './_tests/fake-ses-endpoint'
import { SANDBOX_FROM_ADDRESS, useSandboxWorld } from './_tests/sandbox-world'
import { SandboxEmailEvents } from './sandbox-email-events'

jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: jest.fn().mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }]),
        resolve4: jest.fn().mockResolvedValue(['1.2.3.4']),
        resolve6: jest.fn().mockResolvedValue([]),
    })),
}))

jest.setTimeout(20000)

const hideIntegrationsFromReplica = (postgres: PostgresRouter, ids: number[]): void => {
    const query = postgres.query.bind(postgres)
    jest.spyOn(postgres, 'query').mockImplementation(async (target, queryString, values, tag, logLevel) => {
        const result = await query(target, queryString, values, tag, logLevel)
        if (target === PostgresUse.COMMON_READ && tag === 'fetchIntegrations') {
            return { ...result, rows: result.rows.filter((row) => !ids.includes(row.id)) }
        }
        return result
    })
}

describe('a transactional email sent from code on the sandbox sender', () => {
    const world = useSandboxWorld()
    let hub: Hub
    let api: CdpApi
    let app: express.Application
    let server: Server
    let queued: CyclotronJobInvocation[]
    let hogFlow: HogFlow
    let sandboxSenderId: number
    let clickhouse: ClickHouseClient

    let member: string
    const content = { subject: 'Your sign-in code', html: '<p>Your code is 123456</p>', text: 'Your code is 123456' }

    beforeAll(async () => {
        hub = await createHub({ SITE_URL: 'http://localhost:8000', WORKFLOWS_SANDBOX_SENDER_ENABLED: true })
        queued = []
        api = new CdpApi(
            hub,
            { ...createCdpConsumerDeps(hub), idempotencyValkey: createIdempotencyValkeyPool(hub) },
            {
                hogQueue: createMockJobQueue(),
                hogflowQueue: {
                    ...createMockJobQueue(),
                    queueInvocations: (invocations: CyclotronJobInvocation[]) => {
                        queued.push(...invocations.map((invocation) => parseJSON(JSON.stringify(invocation))))
                        return Promise.resolve()
                    },
                },
            }
        )
        clickhouse = Clickhouse.createClient()
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    })

    afterAll(async () => {
        server.close()
        await clickhouse.close()
        await closeHub(hub)
    })

    type FlowEmail = Parameters<FixtureHogFlowBuilder['withWorkflow']>[0]['actions'][string]

    const codeSendEmail: FlowEmail = {
        type: 'function_email',
        config: {
            template_id: 'template-email',
            inputs: {},
            message_category_type: 'transactional',
        },
    }

    const insertFlow = (email: FlowEmail = codeSendEmail): Promise<HogFlow> =>
        insertHogFlow(
            world.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(world.team.id)
                .withStatus('active')
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        email,
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'email', type: 'continue' },
                        { from: 'email', to: 'exit', type: 'continue' },
                    ],
                })
                .build()
        )

    beforeEach(async () => {
        mockProducerObserver.resetKafkaProducer()
        queued.length = 0
        hub.WORKFLOWS_SANDBOX_SENDER_ENABLED = true
        hub.HOG_INVOCATION_RESULTS_ENABLED = false
        hub.SES_SANDBOX_TENANT_NAME = world.tenantName
        member = `member-${new UUIDT().toString()}@example.com`
        await world.addMember(member)
        sandboxSenderId = await sandboxSenderOf(world.team.id)
        hogFlow = await insertFlow()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const sandboxSenderOf = async (teamId: number): Promise<number> => {
        const { rows } = await world.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT id FROM posthog_integration WHERE team_id = $1 AND kind = 'email_sandbox'`,
            [teamId],
            'test:sandbox-sender-id'
        )
        return rows[0].id
    }

    const sendFromCode = (payload: Record<string, unknown>) =>
        supertest(app)
            .post(`/api/projects/${world.team.id}/hog_flows/${hogFlow.id}/transactional_email/send`)
            .set({
                Authorization: `Bearer ${jwt.sign(
                    { team_id: world.team.id, hog_flow_id: hogFlow.id, kind: 'code_send' },
                    hub.WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET,
                    { audience: 'posthog:workflows:send_transactional_email', expiresIn: '2m' }
                )}`,
            })
            .send(payload)

    const sandboxSend = (overrides: Record<string, unknown> = {}) => ({
        content,
        from: { integrationId: sandboxSenderId },
        tracking: { captureEngagement: true },
        ...overrides,
    })

    const request = (send: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
        to: member,
        distinct_id: member,
        variables: {},
        send,
        ...extra,
    })

    const roundTrip = (invocation: CyclotronJobInvocation): CyclotronJobInvocation =>
        parseJSON(JSON.stringify(invocation))

    const deliver = async (
        job: CyclotronJobInvocation,
        prepare: (invocation: CyclotronJobInvocation) => void = () => {}
    ): Promise<CyclotronJobInvocationResult[]> => {
        const deps = {
            ...createCdpConsumerDeps(hub),
            sandboxEmail: {
                service: world.service(),
                events: new SandboxEmailEvents(hub.teamManager),
                sesBucket: world.sesBucket(100),
            },
        }
        const workers = {
            email: new CdpCyclotronWorkerEmail(hub, deps, createMockJobQueue()),
            emailsandbox: new CdpCyclotronWorkerEmailSandbox(hub, deps, createMockJobQueue()),
            hogflow: new CdpCyclotronWorkerHogFlow(hub, deps, createMockJobQueue()),
        } as Record<string, { processBatch: CdpCyclotronWorkerEmail['processBatch'] }>
        const results: CyclotronJobInvocationResult[] = []
        let next: CyclotronJobInvocation | null = job
        while (next && results.length < 30) {
            const invocation = roundTrip(next)
            prepare(invocation)
            const batch: Awaited<ReturnType<CdpCyclotronWorkerEmail['processBatch']>> = await workers[
                next.queue
            ].processBatch([invocation])
            await batch.backgroundTask
            const [result] = batch.invocationResults
            results.push(result)
            next = result.finished || result.error ? null : result.invocation
        }
        return results
    }

    const deliveryStatuses = (messageId: string): { status: string; reason: string }[] =>
        mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_EMAIL_STATUS)
            .map(({ value }) => value as { message_id: string; status: string; reason: string })
            .filter((row) => row.message_id === messageId && row.status !== 'queued')
            .map(({ status, reason }) => ({ status, reason }))

    const finalStatus = (messageId: string): string | undefined =>
        mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_EMAIL_STATUS)
            .map(({ value }) => value as { message_id: string; status: string; version: string })
            .filter((row) => row.message_id === messageId)
            .sort((a, b) => (BigInt(a.version) < BigInt(b.version) ? -1 : 1))
            .at(-1)?.status

    const metricNames = (results: CyclotronJobInvocationResult[]): MinimalAppMetric['metric_name'][] =>
        results.flatMap((result) => result.metrics ?? []).map((metric) => metric.metric_name)

    it.each([
        ['', false],
        [' when the replica does not have the new sandbox sender yet', true],
    ])(
        'queues the send on the sandbox sender and delivers the accepted content to the member%s',
        async (_desc, lagging) => {
            if (lagging) {
                hideIntegrationsFromReplica(hub.postgres, [sandboxSenderId])
            }

            const res = await sendFromCode(request(sandboxSend()))

            expect(res.status).toEqual(202)
            expect(res.body).toEqual({
                status: 'queued',
                invocation_id: expect.any(String),
                replayed: false,
                sender_kind: 'email_sandbox',
                attachment_count: 0,
                attachment_bytes: 0,
            })
            expect(queued).toHaveLength(1)

            const results = await deliver(queued[0])

            expect(results.at(-1)).toMatchObject({ finished: true })
            expect(world.ses.delivered).toEqual([
                expect.objectContaining({
                    from: { address: SANDBOX_FROM_ADDRESS, name: `${world.organizationName} via PostHog` },
                    to: [{ name: '', address: member }],
                    subject: content.subject,
                    text: expect.stringContaining(content.text),
                    html: expect.stringContaining(content.html),
                    tenantName: 'sandbox-tenant',
                }),
            ])
            expect(metricNames(results)).toContain('email_sandbox_sent')
            expect(metricNames(results)).not.toContain('billable_invocation')
            expect(deliveryStatuses(queued[0].id)).toEqual([{ status: 'sent', reason: '' }])
        }
    )

    const runLogs = (results: CyclotronJobInvocationResult[]): string[] =>
        results.flatMap((result) => result.logs).map((log) => log.message)

    it.each<[string, string, () => Promise<unknown>]>([
        [
            'the member left',
            'not_member',
            () =>
                world.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_user SET is_active = false WHERE email = $1`,
                    [member],
                    'test:member-left'
                ),
        ],
        [
            'staff suspended the project',
            'sending_suspended',
            () =>
                world.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspended_at, email_sending_suspension_reason)
                     VALUES ($1, false, 'off', now(), 'testing suspension')
                     ON CONFLICT (team_id) DO UPDATE SET email_sending_suspended_at = now()`,
                    [world.team.id],
                    'test:suspend-email-sending'
                ),
        ],
        [
            "the workflow's email was paused",
            'sending_paused',
            () =>
                world.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_hogflow SET email_sending_paused_at = now() WHERE id = $1`,
                    [hogFlow.id],
                    'test:pause-workflow-email'
                ),
        ],
    ])('rechecks at delivery and sends nothing when %s after the send was queued', async (_desc, reason, arrange) => {
        const res = await sendFromCode(request(sandboxSend()))
        expect(res.status).toEqual(202)
        await arrange()

        const results = await deliver(queued[0])

        expect(world.ses.delivered).toEqual([])
        expect(results.at(-1)).toMatchObject({ finished: true })
        expect(metricNames(results)).toContain('email_sandbox_blocked')
        expect(runLogs(results)).toContainEqual(expect.stringContaining(`not sent (skipped): ${reason}`))
        expect(deliveryStatuses(queued[0].id)).toEqual([{ status: 'failed', reason }])
    })

    it('records a send as failed and sends nothing when the sandbox sender is switched off after the send was queued', async () => {
        const res = await sendFromCode(request(sandboxSend()))
        expect(res.status).toEqual(202)
        hub.WORKFLOWS_SANDBOX_SENDER_ENABLED = false

        const results = await deliver(queued[0])

        expect(world.ses.delivered).toEqual([])
        expect(results.at(-1)).toMatchObject({ finished: true })
        expect(runLogs(results)).toContainEqual(expect.stringContaining('not sent (skipped): sending_disabled'))
        expect(deliveryStatuses(queued[0].id)).toEqual([{ status: 'failed', reason: 'sending_disabled' }])
    })

    it('keeps the sent status when the run is canceled after SES accepted the send', async () => {
        const res = await sendFromCode(request(sandboxSend()))
        expect(res.status).toEqual(202)
        let sent = false

        const results = await deliver(queued[0], (invocation) => {
            sent ||= world.ses.delivered.length > 0
            if (sent && invocation.queue === 'hogflow') {
                invocation.cancelRequestedAt = DateTime.now()
            }
        })

        expect(world.ses.delivered).toHaveLength(1)
        expect(results.at(-1)).toMatchObject({ canceled: true })
        expect(finalStatus(queued[0].id)).toEqual('sent')
    })

    it.each<[string, () => void, number, { status: string; reason: string }]>([
        [
            'SES rejects the send',
            () => world.ses.replyNext(SES_REJECTED),
            0,
            { status: 'failed', reason: 'ses_rejected' },
        ],
        ['SES throttles the first attempt', () => world.ses.replyNext(SES_THROTTLE), 1, { status: 'sent', reason: '' }],
        [
            'SES throttles every attempt',
            () => world.ses.replyAlways(SES_THROTTLE),
            0,
            { status: 'failed', reason: 'retries_exhausted' },
        ],
    ])('records only the final status when %s', async (_desc, arrange, delivered, final) => {
        const res = await sendFromCode(request(sandboxSend()))
        expect(res.status).toEqual(202)
        arrange()

        const results = await deliver(queued[0])

        expect(world.ses.delivered).toHaveLength(delivered)
        expect(results.at(-1)).toMatchObject({ finished: true })
        expect(deliveryStatuses(queued[0].id)).toEqual([final])
    })

    const rerunFromStoredRun = async (invocationId: string): Promise<CyclotronJobInvocation[]> => {
        await clickhouse.insert({
            table: 'hog_invocation_results',
            values: mockProducerObserver
                .getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)
                .map(({ value }) => value as Record<string, unknown>)
                .filter((row) => row.invocation_id === invocationId),
            format: 'JSONEachRow',
        })
        const rerunQueued: CyclotronJobInvocation[] = []
        const services = createCdpCoreServices(hub, createCdpConsumerDeps(hub))
        const paginator = new RerunPaginatorService(
            clickhouse,
            services.hogFunctionManager,
            services.hogFlowManager,
            services.invocationResultsService.invocationResultsRowsService,
            {
                hog_function: createMockJobQueue(),
                hog_flow: {
                    ...createMockJobQueue(),
                    queueInvocations: (invocations: CyclotronJobInvocation[]) => {
                        rerunQueued.push(...invocations.map(roundTrip))
                        return Promise.resolve()
                    },
                },
            } as unknown as RerunJobQueues,
            services.invocationResultsService.monitoringService,
            10000
        )
        await paginator.processPage(
            world.team.id,
            {
                function_kind: 'hog_flow',
                function_id: hogFlow.id,
                request: {
                    filter: {
                        window_start: '2020-01-01T00:00:00Z',
                        window_end: '2100-01-01T00:00:00Z',
                        status: ['failed', 'canceled'],
                    },
                    replay_code_sends: true,
                },
                progress: { queued: 0, skipped: 0, done: false },
            },
            { jobId: `rerun-${new UUIDT().toString()}`, createdAt: DateTime.now() }
        )
        return rerunQueued
    }

    const cancelOnceSent = (): ((invocation: CyclotronJobInvocation) => void) => {
        let sent = false
        return (invocation) => {
            sent ||= world.ses.delivered.length > 0
            if (sent && invocation.queue === 'hogflow') {
                invocation.cancelRequestedAt = DateTime.now()
            }
        }
    }

    const rerunCases: [string, (job: CyclotronJobInvocation) => Promise<unknown>, () => void, number][] = [
        ['SES rejected the send', (job) => (world.ses.replyNext(SES_REJECTED), deliver(job)), () => {}, 0],
        [
            'SES throttled every attempt',
            (job) => (world.ses.replyAlways(SES_THROTTLE), deliver(job)),
            () => (world.ses.replyAlways(null), world.ses.replyNext(SES_THROTTLE)),
            0,
        ],
        ['SES accepted the send and the run was canceled', (job) => deliver(job, cancelOnceSent()), () => {}, 1],
    ]

    const expectOneDeliveryToMember = (): void =>
        expect(world.ses.delivered).toEqual([
            expect.objectContaining({
                from: { address: SANDBOX_FROM_ADDRESS, name: `${world.organizationName} via PostHog` },
                to: [{ name: '', address: member }],
                subject: content.subject,
            }),
        ])

    it.each(rerunCases)(
        'delivers a rerun on the sandbox sender exactly once after %s',
        async (_desc, firstRun, beforeRerun, sentBeforeRerun) => {
            hub.HOG_INVOCATION_RESULTS_ENABLED = true
            hogFlow = await insertFlow({ ...codeSendEmail, on_error: 'abort' })
            const res = await sendFromCode(request(sandboxSend()))
            expect(res.status).toEqual(202)
            await firstRun(queued[0])
            expect(world.ses.delivered).toHaveLength(sentBeforeRerun)
            beforeRerun()

            const rerun = await rerunFromStoredRun(queued[0].id)
            expect(rerun).toHaveLength(1)
            const results = await deliver(rerun[0])

            expect(results.at(-1)).toMatchObject({ finished: true })
            expectOneDeliveryToMember()
            expect(finalStatus(queued[0].id)).toEqual('sent')
        }
    )

    it.each(rerunCases)(
        'delivers a rerun of a workflow sandbox email step exactly once after %s',
        async (_desc, firstRun, beforeRerun, sentBeforeRerun) => {
            hub.HOG_INVOCATION_RESULTS_ENABLED = true
            hogFlow = await insertFlow({
                type: 'email_sandbox',
                on_error: 'abort',
                config: {
                    inputs: {
                        email: {
                            templating: 'liquid',
                            value: { to: { email: member }, subject: content.subject, text: content.text },
                        },
                    },
                },
            })
            const job: CyclotronJobInvocation = {
                id: new UUIDT().toString(),
                teamId: world.team.id,
                functionId: hogFlow.id,
                queue: 'hogflow',
                queuePriority: 1,
                state: createHogFlowInvocationContext({
                    event: { distinct_id: member, properties: {} } as HogFlowInvocationContext['event'],
                }),
            }
            await firstRun(job)
            expect(world.ses.delivered).toHaveLength(sentBeforeRerun)
            beforeRerun()

            const rerun = await rerunFromStoredRun(job.id)
            expect(rerun).toHaveLength(1)
            const results = await deliver(rerun[0])

            expect(results.at(-1)).toMatchObject({ finished: true })
            expectOneDeliveryToMember()
        }
    )

    it.each([
        ['a recipient outside the organization', true],
        ['a member who has not verified their email', false],
    ])('refuses %s', async (_desc, verified) => {
        const recipient = `other-${new UUIDT().toString()}@example.com`
        if (!verified) {
            await world.addMember(recipient, { verified: false })
        }

        const res = await sendFromCode(request(sandboxSend(), { to: recipient, distinct_id: recipient }))

        expect(res.status).toEqual(422)
        expect(res.body).toEqual({ error: 'sandbox_recipient_not_member' })
        expect(queued).toEqual([])
    })

    it.each<[string, (senderId: number) => Record<string, unknown>]>([
        ['cc', () => ({ cc: ['other@example.com'] })],
        ['bcc', () => ({ bcc: ['other@example.com'] })],
        ['a reply-to address', () => ({ replyTo: ['help@example.com'] })],
        ['a custom from address', (integrationId) => ({ from: { integrationId, email: 'me@example.com' } })],
        ['a custom from name', (integrationId) => ({ from: { integrationId, name: 'Support' } })],
    ])('refuses a send with %s instead of dropping it', async (_desc, fields) => {
        const res = await sendFromCode(request(sandboxSend(fields(sandboxSenderId))))

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({ error: 'sandbox_fields_unsupported' })
        expect(queued).toEqual([])
    })

    it.each([
        ['the organization is blocked from the sandbox sender', () => world.blockOrganization()],
        ['the sandbox sender is paused', () => world.setTenant('PAUSED', new Date())],
        [
            'the sandbox sender is off',
            () => {
                hub.WORKFLOWS_SANDBOX_SENDER_ENABLED = false
                return Promise.resolve()
            },
        ],
    ])('refuses the send when %s', async (_desc, arrange) => {
        await arrange()

        const res = await sendFromCode(request(sandboxSend()))

        expect(res.status).toEqual(403)
        expect(res.body).toEqual({ error: 'sandbox_sender_unavailable' })
        expect(queued).toEqual([])
    })

    it("refuses another team's sandbox sender", async () => {
        const other = await createTestTeamFixture(world.postgres)
        const otherSender = await insertIntegration(world.postgres, other.team.id, {
            kind: 'email_sandbox',
            integration_id: 'posthog-managed-sandbox',
            config: {},
        } as any)

        const res = await sendFromCode(request(sandboxSend({ from: { integrationId: otherSender.id } })))

        expect(res.status).toEqual(403)
        expect(res.body).toEqual({ error: 'sandbox_sender_unavailable' })
        expect(queued).toEqual([])
    })

    it('answers a retry with the same key with the sandbox sender kind and queues nothing new', async () => {
        const keyed = request(sandboxSend(), { idempotency_key: `key-${new UUIDT().toString()}` })

        const sent = await sendFromCode(keyed)
        const replayed = await sendFromCode(keyed)

        expect(sent.status).toEqual(202)
        expect(replayed.status).toEqual(202)
        expect(replayed.body).toEqual({
            status: 'queued',
            invocation_id: sent.body.invocation_id,
            replayed: true,
            sender_kind: 'email_sandbox',
            attachment_count: 0,
            attachment_bytes: 0,
        })
        expect(queued).toHaveLength(1)
    })
})
