import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { setupExpressApp } from '~/common/api/router'
import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

import { CyclotronJobInvocationHogFlow } from '../../../types'
import { createInvocationResult } from '../../../utils/invocation-utils'
import { HogInputsService } from '../../hog-inputs.service'
import { ActionHandlerOptions } from '../../hogflows/actions/action.interface'
import { SandboxEmailAction, SandboxEmailStepResult } from '../../hogflows/actions/email_sandbox'
import { RecipientTokensService } from '../recipient-tokens.service'
import { capturedAnalytics, sandboxEventsCapturedInMemory } from './_tests/captured-analytics'
import { SES_REJECTED, SES_SERVER_ERROR, SES_THROTTLE } from './_tests/fake-ses-endpoint'
import { SandboxFaults, useSandboxWorld } from './_tests/sandbox-world'
import { SandboxCaps, claimSandboxCaps } from './sandbox-caps'
import { SANDBOX_TEST_TIMEOUT_MS } from './sandbox-deadlines'
import { SandboxEmailEvents } from './sandbox-email-events'
import { SANDBOX_TEST_SEND_PATH, SandboxEmailTestRouteDeps, sandboxEmailTestRouter } from './sandbox-email-test-route'
import { SandboxEmailTester, SandboxEmailTesterDeps } from './sandbox-email-tester'
import { deliveredAddressReader } from './sandbox-render'
import { SandboxSesBucket, sandboxTestSendBucket } from './sandbox-ses-bucket'

describe('sandbox email test sends', () => {
    const world = useSandboxWorld()
    const secret = 'sandbox-test-secret'
    const workerJwt = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SANDBOX_EMAIL_TEST, secret)
    let hogFlow: HogFlow
    let events: SandboxEmailEvents
    let app: express.Application
    let server: Server

    const member = () => `member-${world.team.id}@example.com`

    const serveWorker = ({
        sendingOn = true,
        faults,
        caps,
        bucket = null,
    }: {
        sendingOn?: boolean
        faults?: SandboxFaults
        caps?: SandboxCaps
        bucket?: SandboxEmailTestRouteDeps['sesBucket']
    } = {}): void => {
        server?.close()
        app = setupExpressApp({ internalApiSecret: 'shared-internal-secret' })
        app.use(
            sandboxEmailTestRouter({
                jwt: workerJwt,
                service: sendingOn ? world.service({ faults, caps }) : null,
                events,
                sesBucket: bucket,
            })
        )
        server = app.listen(0, () => {})
    }

    beforeAll(() => {
        events = sandboxEventsCapturedInMemory(world.postgres)
    })

    beforeEach(async () => {
        await world.addMember(member())
        capturedAnalytics.length = 0
        serveWorker()
        hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                    email: {
                        type: 'email_sandbox',
                        config: {
                            message_category_id: 'news',
                            message_category_type: 'marketing',
                            inputs: {
                                email: {
                                    templating: 'liquid',
                                    value: { to: { email: '{{ person.properties.email }}' }, subject: 'Hi', text: 'x' },
                                },
                            },
                        },
                    },
                },
                edges: [{ from: 'trigger', to: 'email', type: 'continue' }],
            })
            .build()
        hogFlow.team_id = world.team.id
    })

    afterEach(() => {
        server.close()
    })

    const fetchThroughWorker = async (url: string, options: any): Promise<FetchResponse> => {
        const response = await supertest(app)
            .post(new URL(url).pathname)
            .set(options.headers)
            .send(parseJSON(options.body))
        return {
            status: response.status,
            headers: {},
            json: () => Promise.resolve(response.body),
            text: () => Promise.resolve(response.text),
            dump: () => Promise.resolve(),
        }
    }

    const tester = (fetch: SandboxEmailTesterDeps['fetch'] = fetchThroughWorker): SandboxEmailTester =>
        new SandboxEmailTester({
            hogInputsService: new HogInputsService(
                {} as any,
                new RecipientTokensService('00beef0000beef0000beef0000beef00', 'http://localhost:8000'),
                {} as any
            ),
            deliveredAddress: deliveredAddressReader(world.postgres),
            siteUrl: 'http://localhost:8000',
            endpoint: 'http://sandbox-worker.internal',
            jwt: new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SANDBOX_EMAIL_TEST, secret),
            fetch,
        })

    const testRun = (
        hogExecutorOptions: ActionHandlerOptions<SandboxEmailAction>['hogExecutorOptions'] = {},
        email = member()
    ): ActionHandlerOptions<SandboxEmailAction> => {
        const invocation = createExampleHogFlowInvocation(
            hogFlow,
            { currentAction: { id: 'email', startedAtTimestamp: 0 } },
            { properties: { email } }
        )
        return {
            invocation,
            action: hogFlow.actions.find((action) => action.id === 'email') as SandboxEmailAction,
            result: createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {}),
            hogExecutorOptions: { isTest: true, ...hogExecutorOptions },
        }
    }

    it('renders in cdp-api and sends inline on the sandbox worker as a test', async () => {
        await expect(tester().send(testRun())).resolves.toEqual({ status: 'accepted', message_id: 'ses-1' })

        expect(world.ses.delivered).toEqual([
            expect.objectContaining({
                to: [{ name: '', address: member() }],
                subject: 'Hi',
                tags: expect.objectContaining({
                    ph_sbx_team: String(world.team.id),
                    ph_sbx_flow: hogFlow.id,
                    ph_sbx_action: 'email',
                    ph_sbx_test: 'true',
                }),
            }),
        ])
        await waitForExpect(() =>
            expect(capturedAnalytics).toEqual([
                expect.objectContaining({
                    distinctId: world.team.uuid,
                    event: 'workflows sandbox email sent',
                    properties: { team: world.team.uuid, workflow_id: hogFlow.id, action_id: 'email', is_test: true },
                    groups: expect.objectContaining({
                        project: world.team.uuid,
                        organization: world.team.organization_id,
                    }),
                }),
            ])
        )
    })

    it('sends a test of a workflow that is not saved yet', async () => {
        hogFlow.id = 'new'

        await expect(tester().send(testRun())).resolves.toEqual({ status: 'accepted', message_id: 'ses-1' })
        expect(world.ses.delivered.map((email) => email.tags.ph_sbx_flow)).toEqual(['new'])
    })

    it("holds a test to the step's message category", async () => {
        await world.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
             VALUES (gen_random_uuid(), $1, $2, $3, NOW(), NOW(), false)`,
            [world.team.id, member(), JSON.stringify({ news: 'OPTED_OUT' })],
            'test:opt-out'
        )

        await expect(tester().send(testRun())).resolves.toEqual({ status: 'skipped', reason: 'opted_out' })
        expect(world.ses.delivered).toEqual([])
    })

    it('reports a retryable refusal from the worker as pending', async () => {
        serveWorker({ faults: { capsLimiter: world.unreachableLimiter() } })

        await expect(tester().send(testRun())).resolves.toEqual({
            status: 'pending',
            reason: 'cap_storage_unavailable',
        })
        expect(world.ses.delivered).toEqual([])
    })

    it('reports a block from the worker', async () => {
        await expect(tester().send(testRun({}, 'stranger@example.com'))).resolves.toEqual({
            status: 'skipped',
            reason: 'not_member',
        })
        expect(world.ses.delivered).toEqual([])
    })

    it('skips the test when the worker has sending off', async () => {
        serveWorker({ sendingOn: false })

        await expect(tester().send(testRun())).resolves.toEqual({ status: 'skipped', reason: 'sending_disabled' })
        expect(world.ses.delivered).toEqual([])
    })

    it('takes one slot of the SES send rate that queued sends share for each test it sends, and sends nothing once it is spent', async () => {
        serveWorker({ bucket: world.sesBucket(2) })

        const answers = []
        for (let send = 0; send < 3; send++) {
            answers.push(await tester().send(testRun()))
        }

        expect(answers).toEqual([
            expect.objectContaining({ status: 'accepted' }),
            expect.objectContaining({ status: 'accepted' }),
            { status: 'failed', reason: 'send_rate_limited' },
        ])
        expect(world.ses.attempts).toBe(2)
    })

    it.each<[string, (bucket: SandboxSesBucket) => Promise<unknown>, SandboxEmailStepResult, SandboxEmailStepResult]>([
        [
            'the SES send rate refused it',
            (bucket) => world.takeSlotsLeft(bucket),
            { status: 'failed', reason: 'send_rate_limited' },
            { status: 'accepted', message_id: 'ses-1' },
        ],
        [
            'SES throttled it',
            () => Promise.resolve(world.ses.replyNext(SES_THROTTLE)),
            { status: 'pending', reason: 'ses_throttled' },
            { status: 'accepted', message_id: 'ses-1' },
        ],
        [
            'SES rejected it',
            () => Promise.resolve(world.ses.replyNext(SES_REJECTED)),
            { status: 'failed', reason: 'ses_rejected' },
            { status: 'accepted', message_id: 'ses-1' },
        ],
        [
            'SES failed in a way that may have sent it',
            () => Promise.resolve(world.ses.replyNext(SES_SERVER_ERROR)),
            { status: 'pending', reason: 'ses_transient' },
            { status: 'skipped', reason: 'daily_cap_reached' },
        ],
    ])(
        'charges the daily allowances of a test only when SES may have taken it, after %s',
        async (_case, arrange, first, next) => {
            const bucket = world.sesBucket(1)
            serveWorker({ bucket, caps: { team: 1, recipient: 1 } })
            await arrange(bucket)

            await expect(tester().send(testRun())).resolves.toEqual(first)
            await deleteKeysWithPrefix(world.valkey, bucket.key)

            await expect(tester().send(testRun())).resolves.toEqual(next)
        }
    )

    it.each<[string, () => Promise<string>]>([
        [
            'its organization is blocked',
            async () => {
                await world.blockOrganization()
                return member()
            },
        ],
        ['its recipient is not a member', () => Promise.resolve(`stranger-${world.team.id}@example.com`)],
        [
            "the member's daily allowance is spent",
            async () => {
                await claimSandboxCaps(
                    world.limiter('sandbox-email-caps'),
                    { team: 5, recipient: 1 },
                    {
                        organizationId: world.organizationId,
                        teamId: world.team.id,
                        storedAddress: member(),
                        claimId: 'an earlier send today',
                    }
                )
                return member()
            },
        ],
    ])('leaves the shared SES send rate untouched by tests it refuses because %s', async (_reason, arrange) => {
        const bucket = world.sesBucket(2)
        serveWorker({ bucket, caps: { team: 5, recipient: 1 } })
        const recipient = await arrange()

        for (let send = 0; send < 3; send++) {
            await expect(tester().send(testRun({}, recipient))).resolves.toMatchObject({ status: 'skipped' })
        }

        expect(await world.takeSlotsLeft(bucket)).toBe(2)
        expect(world.ses.attempts).toBe(0)
    })

    it.each<[string, string, () => Promise<void>]>([
        ["staff suspended the project's email", 'sending_suspended', () => world.suspendProjectEmail()],
        [
            "the workflow's email is paused",
            'sending_paused',
            () => {
                hogFlow.email_sending_paused_at = new Date().toISOString()
                return Promise.resolve()
            },
        ],
    ])(
        'refuses a test send while %s, without spending a daily allowance, an SES slot or an SES attempt',
        async (_name, reason, arrange) => {
            const bucket = world.sesBucket(2)
            const caps = { team: 1, recipient: 1 }
            serveWorker({ bucket, caps })
            await arrange()

            await expect(tester().send(testRun())).resolves.toEqual({ status: 'skipped', reason })

            expect(world.ses.attempts).toBe(0)
            expect(await world.takeSlotsLeft(bucket)).toBe(2)
            expect(await world.allowanceLeft(caps, member())).toBe(true)
        }
    )

    it('refuses a test send while the SES send rate cannot be read', async () => {
        serveWorker({ bucket: { ...world.sesBucket(5), limiter: world.unreachableLimiter() } })

        await expect(tester().send(testRun())).resolves.toEqual({ status: 'failed', reason: 'send_rate_limited' })
        expect(world.ses.delivered).toEqual([])
    })

    it('refuses a test send before the editor stops waiting when the SES send rate store stops answering, and sends on a fresh connection once it answers', async () => {
        const store = new StallingValkeyProxy({
            host: defaultConfig.CDP_REDIS_HOST,
            port: defaultConfig.CDP_REDIS_PORT,
        })
        try {
            const bucket = sandboxTestSendBucket({
                ...defaultConfig,
                SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                SES_RATE_LIMITER_VALKEY_PORT: await store.start(),
                SES_RATE_LIMITER_VALKEY_PASSWORD: defaultConfig.CDP_REDIS_PASSWORD,
                SES_RATE_LIMITER_VALKEY_TLS: false,
            })!
            serveWorker({ bucket })
            const answering = { key: world.sesBucket(5).key, requested: 1, capacity: 5, refillPerSecond: 1 }
            expect(await bucket.limiter.claimUpTo(answering)).toBe(1)
            store.stopAnswering()

            let editorGivesUp: NodeJS.Timeout | undefined
            const answer = await Promise.race([
                tester().send(testRun()),
                new Promise((resolve) => {
                    editorGivesUp = setTimeout(
                        () => resolve('no answer before the editor gave up'),
                        SANDBOX_TEST_TIMEOUT_MS
                    )
                }),
            ]).finally(() => clearTimeout(editorGivesUp))

            expect(answer).toEqual({ status: 'failed', reason: 'send_rate_limited' })
            expect(world.ses.delivered).toEqual([])

            store.answerNewConnections()
            await expect(tester().send(testRun())).resolves.toMatchObject({ status: 'accepted' })
        } finally {
            store.stopLeavingClientsSilent()
        }
    })

    it.each([
        ['no token', undefined],
        ['a token for another audience', new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_STEP_RESUME, secret)],
        ['a token signed with another key', new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SANDBOX_EMAIL_TEST, 'x')],
    ])('refuses a request with %s', async (_name, jwt) => {
        const token = jwt?.mint({ team_id: hogFlow.team_id, hog_flow_id: hogFlow.id })
        const request = supertest(app).post(SANDBOX_TEST_SEND_PATH.replace(':team_id', String(hogFlow.team_id)))

        const response = await (token ? request.set('Authorization', `Bearer ${token}`) : request).send({
            hog_flow_id: hogFlow.id,
            action_id: 'email',
            email: { to: { email: member() }, subject: 'Hi', text: 'x' },
        })

        expect(response.status).toBe(403)
        expect(world.ses.delivered).toEqual([])
    })

    it('asks for the internal secret on a path below the test send route, even with a valid token', async () => {
        const response = await supertest(app)
            .post(`${SANDBOX_TEST_SEND_PATH.replace(':team_id', String(hogFlow.team_id))}/extra`)
            .set('Authorization', `Bearer ${workerJwt.mint({ team_id: hogFlow.team_id, hog_flow_id: hogFlow.id })}`)
            .send({ hog_flow_id: hogFlow.id, action_id: 'email', email: { to: { email: member() } } })

        expect({ status: response.status, body: response.body }).toEqual({
            status: 401,
            body: { error: 'Unauthorized: Missing authentication header' },
        })
    })

    it.each([
        ['a token for another team', (teamId: number) => ({ team_id: teamId + 1, hog_flow_id: hogFlow.id }), 60],
        [
            'a token for another workflow',
            (teamId: number) => ({ team_id: teamId, hog_flow_id: '0190f0f0-0000-7000-8000-00000000000f' }),
            60,
        ],
        ['an expired token', (teamId: number) => ({ team_id: teamId, hog_flow_id: hogFlow.id }), -120],
    ])('refuses %s', async (_name, claims, ttlSeconds) => {
        const token = workerJwt.mint(claims(hogFlow.team_id), ttlSeconds)

        const response = await supertest(app)
            .post(SANDBOX_TEST_SEND_PATH.replace(':team_id', String(hogFlow.team_id)))
            .set('Authorization', `Bearer ${token}`)
            .send({
                hog_flow_id: hogFlow.id,
                action_id: 'email',
                email: { to: { email: member() }, subject: 'Hi', text: 'x' },
            })

        expect(response.status).toBe(403)
        expect(world.ses.delivered).toEqual([])
    })

    it('mocks a test run after rendering, and sends nothing', async () => {
        await expect(tester().send(testRun({ functions: {} }))).resolves.toEqual({ status: 'accepted' })

        const action = hogFlow.actions.find((candidate) => candidate.id === 'email')!
        ;(action.config as any).inputs.email.value.subject = ''
        const failedRun = testRun({ functions: {} })
        await expect(tester().send(failedRun)).resolves.toEqual({ status: 'failed', reason: 'render_failed' })
        expect(world.ses.delivered).toEqual([])
        expect(failedRun.result.logs.map(({ level, message }) => [level, message])).toContainEqual([
            'error',
            expect.stringContaining('failed to render: The rendered sandbox email is missing a recipient, subject'),
        ])
    })

    it.each<[string, () => Promise<FetchResponse>]>([
        ['before its headers', () => Promise.reject(new Error('timeout'))],
        [
            'after its headers',
            () =>
                Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.reject(new Error('timeout')),
                    text: () => Promise.reject(new Error('timeout')),
                    dump: () => Promise.resolve(),
                }),
        ],
    ])('reports a test the worker stops answering %s as pending, never as sent', async (_name, respond) => {
        await expect(tester(respond).send(testRun())).resolves.toEqual({
            status: 'pending',
            reason: 'sandbox_worker_unreachable',
        })
    })
})
