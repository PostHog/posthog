import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { Server } from 'http'
import jwt from 'jsonwebtoken'
import supertest from 'supertest'
import express from 'ultimate-express'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { HogFlow } from '~/cdp/schema/hogflow'
import { setupExpressApp } from '~/common/api/router'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { FixtureHogFlowBuilder } from '../../../_tests/builders/hogflow.builder'
import { insertHogFlow } from '../../../_tests/fixtures-hogflows'
import { CdpApi } from '../../../cdp-api'
import { CdpCyclotronWorkerEmailSandbox } from '../../../consumers/cdp-cyclotron-worker-email-sandbox.consumer'
import { CdpCyclotronWorkerEmail } from '../../../consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from '../../../consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, MinimalAppMetric } from '../../../types'
import { createIdempotencyValkeyPool } from '../../hogflows/idempotency-keys'
import { SANDBOX_FROM_ADDRESS, useSandboxWorld } from './_tests/sandbox-world'
import { SandboxEmailEvents } from './sandbox-email-events'

jest.setTimeout(20000)

describe('a transactional email sent from code on the sandbox sender', () => {
    const world = useSandboxWorld()
    let hub: Hub
    let api: CdpApi
    let app: express.Application
    let server: Server
    let queued: CyclotronJobInvocation[]
    let hogFlow: HogFlow
    let sandboxSenderId: number

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
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    })

    afterAll(async () => {
        server.close()
        await closeHub(hub)
    })

    beforeEach(async () => {
        queued.length = 0
        hub.WORKFLOWS_SANDBOX_SENDER_ENABLED = true
        hub.SES_SANDBOX_TENANT_NAME = world.tenantName
        // example.com publishes a null MX, which the endpoint's own reachability check would refuse.
        jest.spyOn(api['emailValidationService'], 'getRecipientSkipReason').mockResolvedValue(null)
        member = `member-${new UUIDT().toString()}@example.com`
        await world.addMember(member)
        sandboxSenderId = await sandboxSenderOf(world.team.id)
        hogFlow = await insertHogFlow(
            world.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(world.team.id)
                .withStatus('active')
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        email: {
                            type: 'function_email',
                            config: {
                                template_id: 'template-email',
                                inputs: {},
                                message_category_type: 'transactional',
                            },
                        },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'email', type: 'continue' },
                        { from: 'email', to: 'exit', type: 'continue' },
                    ],
                })
                .build()
        )
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
                    'local-dev-workflows-transactional-email-jwt',
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

    const deliver = async (job: CyclotronJobInvocation): Promise<CyclotronJobInvocationResult[]> => {
        const deps = {
            ...createCdpConsumerDeps(hub),
            sandboxEmail: { service: world.service(), events: new SandboxEmailEvents(hub.teamManager) },
        }
        const workers = {
            email: new CdpCyclotronWorkerEmail(hub, deps, createMockJobQueue()),
            emailsandbox: new CdpCyclotronWorkerEmailSandbox(hub, deps, createMockJobQueue()),
            hogflow: new CdpCyclotronWorkerHogFlow(hub, deps, createMockJobQueue()),
        } as Record<string, { processInvocations: CdpCyclotronWorkerEmail['processInvocations'] }>
        const results: CyclotronJobInvocationResult[] = []
        let next: CyclotronJobInvocation | null = job
        while (next && results.length < 6) {
            const [result] = await workers[next.queue].processInvocations([roundTrip(next)])
            results.push(result)
            next = result.finished || result.error ? null : result.invocation
        }
        return results
    }

    const metricNames = (results: CyclotronJobInvocationResult[]): MinimalAppMetric['metric_name'][] =>
        results.flatMap((result) => result.metrics ?? []).map((metric) => metric.metric_name)

    it('queues the send on the sandbox sender and delivers the accepted content to the member', async () => {
        const res = await sendFromCode(request(sandboxSend()))

        expect(res.status).toEqual(202)
        expect(res.body).toEqual({
            status: 'queued',
            invocation_id: expect.any(String),
            replayed: false,
            sender_kind: 'email_sandbox',
        })
        expect(queued).toHaveLength(1)

        const results = await deliver(queued[0])

        expect(results.map((result) => result.invocation.queue)).toEqual(['emailsandbox', 'hogflow', 'hogflow'])
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
    })

    it('rechecks membership at delivery and sends nothing to a member who left after the send was queued', async () => {
        const res = await sendFromCode(request(sandboxSend()))
        expect(res.status).toEqual(202)
        await world.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_user SET is_active = false WHERE email = $1`,
            [member],
            'test:member-left'
        )

        const results = await deliver(queued[0])

        expect(world.ses.delivered).toEqual([])
        expect(metricNames(results)).toContain('email_sandbox_blocked')
    })

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
        })
        expect(queued).toHaveLength(1)
    })
})
