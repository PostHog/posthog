import { SESv2Client } from '@aws-sdk/client-sesv2'
import { DateTime } from 'luxon'
import { AddressInfo, Server, Socket, createServer } from 'net'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { parseJSON } from '~/common/utils/json-parse'
import { PubSub } from '~/common/utils/pubsub'
import { waitForExpect } from '~/tests/helpers/expectations'
import { RedisPool } from '~/types'

import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../../../types'
import { HogInputsService } from '../../hog-inputs.service'
import { HogFlowExecutorService } from '../../hogflows/hogflow-executor.service'
import { TeamWorkflowsConfigService } from '../../managers/team-workflows-config.service'
import { RecipientPreferencesService } from '../recipient-preferences.service'
import { RecipientTokensService } from '../recipient-tokens.service'
import { capturedAnalytics, sandboxEventsCapturedInMemory } from './_tests/captured-analytics'
import { SES_REJECTED, SES_THROTTLE, SesReply } from './_tests/fake-ses-endpoint'
import { SandboxFaults, useSandboxWorld } from './_tests/sandbox-world'
import { claimSandboxCaps } from './sandbox-caps'
import { SandboxEmailEvents } from './sandbox-email-events'
import { MAX_SANDBOX_RETRIES, SandboxEmailSendStep } from './sandbox-email-step'
import { DeliveredAddressReader, deliveredAddressReader } from './sandbox-render'
import { SandboxSesBucket, sandboxWorkerSesBucket } from './sandbox-ses-bucket'
import { SandboxSesClient } from './sandbox-ses-client'

describe('SandboxEmailSendStep', () => {
    const world = useSandboxWorld()
    const tokens = new RecipientTokensService('00beef0000beef0000beef0000beef00', 'http://localhost:8000')
    const caps = { team: 5, recipient: 1 }
    let hogFlow: HogFlow
    let events: SandboxEmailEvents
    let pubSubPool: RedisPool
    let pubSub: PubSub
    let sesBucket: SandboxSesBucket

    const member = () => `Member-${world.team.id}@Example.com`
    const frequencyCapKeys = () => `@posthog/workflows-frequency-cap/${world.team.id}/`

    beforeAll(async () => {
        events = sandboxEventsCapturedInMemory(world.postgres)
        pubSubPool = createRedisPoolFromConfig({
            connection: { url: defaultConfig.REDIS_URL },
            poolMinSize: 1,
            poolMaxSize: 2,
        })
        pubSub = new PubSub(pubSubPool)
        await pubSub.start()
    })

    afterAll(async () => {
        await pubSub.stop()
        await pubSubPool.drain()
        await pubSubPool.clear()
    })

    afterEach(async () => {
        await deleteKeysWithPrefix(world.valkey, frequencyCapKeys())
    })

    beforeEach(async () => {
        await world.addMember(member())
        capturedAnalytics.length = 0
        sesBucket = world.sesBucket(100)
        hogFlow = new FixtureHogFlowBuilder()
            .withExitCondition('exit_only_at_end')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    email: {
                        type: 'email_sandbox',
                        output_variable: { key: 'email_result' },
                        config: {
                            inputs: {
                                email: {
                                    templating: 'liquid',
                                    value: {
                                        to: { email: '{{ person.properties.email }}' },
                                        subject: 'Hi {{ person.properties.name }}',
                                        text: 'Hello. Unsubscribe: {{ unsubscribe_url_one_click }}',
                                    },
                                },
                            },
                        },
                    },
                    wait: { type: 'delay', config: { delay_duration: '1h' } },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'email', type: 'continue' },
                    { from: 'email', to: 'wait', type: 'continue' },
                    { from: 'wait', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        hogFlow.team_id = world.team.id
        hogFlow.version = 3
    })

    const recipientPreferences = (): RecipientPreferencesService =>
        new RecipientPreferencesService(world.recipients, world.suppression, {
            teamWorkflowsConfig: new TeamWorkflowsConfigService(world.postgres, pubSub),
            valkey: world.valkey,
            persons: {
                getCyclotronPerson: () => Promise.reject(new Error('a sandbox email caps the run person')),
            },
        })

    const buildExecutor = (
        dailyCaps = caps,
        deliveredAddress: DeliveredAddressReader = deliveredAddressReader(world.postgres),
        faults?: SandboxFaults
    ): HogFlowExecutorService => {
        const step = new SandboxEmailSendStep({
            service: world.service({ caps: dailyCaps, faults }),
            hogInputsService: new HogInputsService({} as any, tokens, {} as any),
            deliveredAddress,
            siteUrl: 'http://localhost:8000',
            recipientPreferences: recipientPreferences(),
            events,
            sesBucket,
        })
        return new HogFlowExecutorService(
            {} as any,
            {} as any,
            {} as any,
            {} as any,
            {} as any,
            null,
            undefined,
            undefined,
            { sandboxEmail: { enabled: true, send: step } }
        )
    }

    const runFor = (email: string): CyclotronJobInvocationHogFlow => {
        const invocation = createExampleHogFlowInvocation(
            hogFlow,
            { currentAction: { id: 'email', startedAtTimestamp: Date.now() } },
            { properties: { email, name: 'Mem' } }
        )
        invocation.queue = 'hogflow'
        return invocation
    }

    const nextDequeue = (invocation: CyclotronJobInvocationHogFlow): CyclotronJobInvocationHogFlow => ({
        ...invocation,
        state: parseJSON(JSON.stringify(invocation.state)),
        queueScheduledAt: undefined,
    })

    const runSandboxQueue = async (
        executor: HogFlowExecutorService,
        routed: CyclotronJobInvocationHogFlow,
        beforeAttempt: (attempt: number) => Promise<void> = () => Promise.resolve()
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]> => {
        const segments: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[] = []
        let next = routed
        do {
            await beforeAttempt(segments.length)
            segments.push(await executor.execute(nextDequeue(next)))
            next = segments.at(-1)!.invocation
        } while (next.queue === 'emailsandbox')
        return segments
    }

    const runToNextAction = async (
        email: string,
        {
            beforeAttempt,
            dailyCaps,
        }: { beforeAttempt?: (attempt: number) => Promise<void>; dailyCaps?: typeof caps } = {}
    ): Promise<{
        segments: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]
        finished: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    }> => {
        const executor = buildExecutor(dailyCaps)
        const routed = await executor.execute(runFor(email))
        const segments = await runSandboxQueue(executor, routed.invocation, beforeAttempt)
        const finished = await executor.execute(nextDequeue(segments.at(-1)!.invocation))
        return { segments, finished }
    }

    const metricNames = (segments: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]) =>
        segments.flatMap((segment) => segment.metrics.map((metric) => [metric.metric_name, metric.instance_id]))

    it('sends nothing on the hogflow queue, sends on the sandbox queue, then runs the next action', async () => {
        const executor = buildExecutor()
        const batchRun = runFor(member().toLowerCase())
        batchRun.parentRunId = 'batch-run-1'

        const routed = await executor.execute(batchRun)
        expect(routed.invocation.queue).toBe('emailsandbox')
        expect(world.ses.delivered).toEqual([])

        const [sent] = await runSandboxQueue(executor, routed.invocation)
        expect(world.ses.delivered).toEqual([
            expect.objectContaining({
                to: [{ name: '', address: member() }],
                subject: 'Hi Mem',
                tags: {
                    ph_sbx_team: String(world.team.id),
                    ph_sbx_flow: hogFlow.id,
                    ph_sbx_run: routed.invocation.id,
                    ph_sbx_action: 'email',
                    ph_sbx_version: '3',
                    ph_sbx_test: 'false',
                    ph_sbx_parent_run: 'batch-run-1',
                },
            }),
        ])
        expect(sent.invocation.queue).toBe('hogflow')
        expect(metricNames([sent])).toEqual([['email_sandbox_sent', 'email']])
        await waitForExpect(() =>
            expect(capturedAnalytics).toEqual([
                expect.objectContaining({
                    distinctId: world.team.uuid,
                    event: 'workflows sandbox email sent',
                    properties: { team: world.team.uuid, workflow_id: hogFlow.id, action_id: 'email', is_test: false },
                    groups: expect.objectContaining({
                        project: world.team.uuid,
                        organization: world.team.organization_id,
                    }),
                }),
            ])
        )

        const finished = await executor.execute(nextDequeue(sent.invocation))
        expect(world.ses.delivered).toHaveLength(1)
        expect(finished.invocation.state.currentAction?.id).toBe('wait')
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'accepted', message_id: 'ses-1' })
    })

    const spendTodaysAllowance = async (): Promise<void> => {
        await claimSandboxCaps(world.limiter('sandbox-email-caps'), caps, {
            organizationId: world.organizationId,
            teamId: world.team.id,
            storedAddress: member(),
            claimId: 'an earlier send today',
        })
    }

    const replies =
        (...sesReplies: SesReply[]) =>
        (): Promise<void> => {
            world.ses.replyNext(...sesReplies)
            return Promise.resolve()
        }

    it.each<[string, () => Promise<void>, object, string, number, number]>([
        [
            'SES rejects the message',
            replies(SES_REJECTED),
            { status: 'failed', reason: 'ses_rejected' },
            'email_sandbox_failed',
            1,
            0,
        ],
        [
            'SES throttles every attempt',
            () => {
                world.ses.replyAlways(SES_THROTTLE)
                return Promise.resolve()
            },
            { status: 'failed', reason: 'retries_exhausted' },
            'email_sandbox_failed',
            MAX_SANDBOX_RETRIES + 1,
            0,
        ],
        [
            'the template renders no subject',
            () => {
                const action = hogFlow.actions.find((candidate) => candidate.id === 'email')!
                ;(action.config as any).inputs.email.value.subject = '{{ person.properties.missing }}'
                return Promise.resolve()
            },
            { status: 'failed', reason: 'render_failed' },
            'email_sandbox_failed',
            0,
            0,
        ],
        [
            "the member's daily allowance is already spent",
            spendTodaysAllowance,
            { status: 'skipped', reason: 'daily_cap_reached' },
            'email_sandbox_blocked',
            0,
            0,
        ],
        [
            'SES throttles once while one daily allowance is left',
            replies(SES_THROTTLE),
            { status: 'accepted', message_id: 'ses-1' },
            'email_sandbox_sent',
            2,
            1,
        ],
        [
            'SES may have accepted a send before failing transiently, while one daily allowance is left',
            replies({ kind: 'drop' }),
            { status: 'skipped', reason: 'daily_cap_reached' },
            'email_sandbox_blocked',
            1,
            0,
        ],
    ])(
        'stores the outcome when %s and continues past it',
        async (_name, arrange, stepResult, metric, sesAttempts, delivered) => {
            await arrange()

            const { segments, finished } = await runToNextAction(member())

            expect(world.ses.attempts).toBe(sesAttempts)
            expect(world.ses.delivered).toHaveLength(delivered)
            expect(await world.takeSlotsLeft(sesBucket)).toBe(sesBucket.capacity - sesAttempts)
            expect(metricNames(segments)).toEqual([[metric, 'email']])
            expect(finished.invocation.state.currentAction?.id).toBe('wait')
            expect(finished.invocation.state.variables?.email_result).toEqual(stepResult)
        }
    )

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
        'skips a step while %s, without spending a daily allowance, an SES slot or an SES attempt',
        async (_name, reason, arrange) => {
            const dailyCaps = { team: 1, recipient: 1 }
            await arrange()

            const { segments, finished } = await runToNextAction(member(), { dailyCaps })

            expect(world.ses.attempts).toBe(0)
            expect(await world.takeSlotsLeft(sesBucket)).toBe(sesBucket.capacity)
            expect(await world.allowanceLeft(dailyCaps, member())).toBe(true)
            expect(metricNames(segments)).toEqual([['email_sandbox_blocked', 'email']])
            expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'skipped', reason })
        }
    )

    it('retries a step while the shared SES send rate is spent, and charges the daily allowance only for the send that goes out', async () => {
        await world.takeSlotsLeft(sesBucket)

        const { segments, finished } = await runToNextAction(member(), {
            beforeAttempt: async (attempt) => {
                if (attempt === 1) {
                    await deleteKeysWithPrefix(world.valkey, sesBucket.key)
                }
            },
        })

        expect(segments).toHaveLength(2)
        expect(world.ses.attempts).toBe(1)
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'accepted', message_id: 'ses-1' })
    })

    it('retries a step without an SES attempt while the SES send rate store stops answering, and sends it once the store answers', async () => {
        const store = new StallingValkeyProxy({
            host: defaultConfig.CDP_REDIS_HOST,
            port: defaultConfig.CDP_REDIS_PORT,
        })
        try {
            const workerBucket = sandboxWorkerSesBucket({
                ...defaultConfig,
                SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                SES_RATE_LIMITER_VALKEY_PORT: await store.start(),
                SES_RATE_LIMITER_VALKEY_PASSWORD: defaultConfig.CDP_REDIS_PASSWORD,
                SES_RATE_LIMITER_VALKEY_TLS: false,
            })
            sesBucket = { ...workerBucket, key: sesBucket.key }
            const executor = buildExecutor()
            const routed = await executor.execute(runFor(member()))
            store.stopAnswering()

            const stalled = await executor.execute(nextDequeue(routed.invocation))

            expect(world.ses.attempts).toBe(0)
            expect(stalled.invocation.queue).toBe('emailsandbox')

            store.answerNewConnections()
            await runSandboxQueue(executor, stalled.invocation)
            expect(world.ses.delivered).toHaveLength(1)
        } finally {
            store.stopLeavingClientsSilent()
        }
    })

    it("retries a step without an SES attempt while the team's email settings wait behind a lock, and sends it once they are read", async () => {
        const executor = buildExecutor(caps, undefined, { teamConfigReadTimeoutMs: 200 })
        const routed = await executor.execute(runFor(member()))
        const release = await world.lockTable('workflows_teamworkflowsconfig')
        let stalled: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
        try {
            stalled = await executor.execute(nextDequeue(routed.invocation))
        } finally {
            await release()
        }

        expect(world.ses.attempts).toBe(0)
        expect(stalled.invocation.queue).toBe('emailsandbox')

        await runSandboxQueue(executor, stalled.invocation)
        expect(world.ses.delivered).toHaveLength(1)
        expect(await world.takeSlotsLeft(sesBucket)).toBe(sesBucket.capacity - 1)
    })

    it('refuses a job redelivered from before its send once SES took the email, reset the connection, and spent the caps', async () => {
        const executor = buildExecutor()
        const routed = await executor.execute(runFor(member()))
        world.ses.replyNext({ kind: 'deliver-then-reset' })

        const lostReply = await executor.execute(nextDequeue(routed.invocation))
        const redelivered = await executor.execute(nextDequeue(routed.invocation))

        expect(lostReply.invocation.queue).toBe('emailsandbox')
        expect(world.ses.attempts).toBe(1)
        expect(world.ses.delivered).toHaveLength(1)
        expect(redelivered.invocation.queue).toBe('hogflow')
        expect(metricNames([redelivered])).toEqual([['email_sandbox_blocked', 'email']])
        const finished = await executor.execute(nextDequeue(redelivered.invocation))
        expect(finished.invocation.state.variables?.email_result).toEqual({
            status: 'skipped',
            reason: 'daily_cap_reached',
        })
    })

    it('settles a batch at the SES deadline when one send never gets its credentials, and sends it on a retry', async () => {
        const roomy = { team: 100, recipient: 100 }
        const workingSes = world.sesClient
        world.sesClient = new SandboxSesClient(
            new SESv2Client({
                region: 'us-east-1',
                endpoint: 'http://127.0.0.1:1',
                maxAttempts: 1,
                credentials: () => new Promise<never>(() => {}),
            }),
            { configurationSet: 'sandbox-config-set', tenantName: 'sandbox-tenant', sendTimeoutMs: 500 }
        )
        const stalledExecutor = buildExecutor(roomy)
        const [toMember, toOutsider] = await Promise.all(
            [member(), `outsider-${world.team.id}@example.com`].map((email) => stalledExecutor.execute(runFor(email)))
        )

        const [stalled, outsider] = await Promise.all(
            [toMember, toOutsider].map((routed) => stalledExecutor.execute(nextDequeue(routed.invocation)))
        )

        expect(world.ses.attempts).toBe(0)
        expect(stalled.invocation.queue).toBe('emailsandbox')
        expect(stalled.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(Date.now())
        expect(outsider.invocation.queue).toBe('hogflow')
        expect(metricNames([outsider])).toEqual([['email_sandbox_blocked', 'email']])

        world.sesClient = workingSes
        const [retried] = await runSandboxQueue(buildExecutor(roomy), stalled.invocation)
        expect(world.ses.delivered).toHaveLength(1)
        expect(metricNames([retried])).toEqual([['email_sandbox_sent', 'email']])
    }, 5_000)

    it('keeps the daily allowance it spent before an SES throttle through a later pause-state outage', async () => {
        world.ses.replyNext(SES_THROTTLE)

        const { finished } = await runToNextAction(member(), {
            beforeAttempt: async (attempt) => {
                if (attempt === 1) {
                    await world.setTenant('ENABLED', new Date(Date.now() - 600_000))
                }
                if (attempt === 2) {
                    await world.setTenant('ENABLED', new Date())
                }
            },
        })

        expect(world.ses.delivered).toHaveLength(1)
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'accepted', message_id: 'ses-1' })
    })

    const unsubscribedIdentifier = (email: { text?: string }): string => {
        const token = new URL(email.text!.match(/https?:\/\/\S+/)![0]).pathname.split('/').filter(Boolean).at(-1)!
        const unsubscribed = tokens.validatePreferencesToken(token)
        expect(unsubscribed.valid).toBe(true)
        return (unsubscribed as { identifier: string }).identifier
    }

    it('honours an unsubscribe from a sandbox email when later emails spell the address differently', async () => {
        const roomy = { dailyCaps: { team: 100, recipient: 100 } }
        await runToNextAction(member().toUpperCase(), roomy)
        await world.recipients.optOut(world.team.id, [unsubscribedIdentifier(world.ses.delivered[0])])

        const { finished } = await runToNextAction(member().toLowerCase(), roomy)

        expect(world.ses.delivered).toHaveLength(1)
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'skipped', reason: 'opted_out' })
    })

    const unsubscribeThroughLink = (email: { text?: string }): Promise<void> =>
        world.recipients.optOut(world.team.id, [unsubscribedIdentifier(email)])

    const ordinaryEmailSkipReason = (address: string): Promise<string | null> => {
        const ordinaryEmail = { id: 'ordinary', type: 'function_email', config: { message_category_type: 'marketing' } }
        const ordinaryRun = {
            teamId: world.team.id,
            state: { globals: { inputs: { email: { to: { email: address } } } } },
        }
        return recipientPreferences().shouldSkipAction(ordinaryRun as any, ordinaryEmail as any)
    }

    it('skips a later ordinary email to the delivered address once the member unsubscribes from a sandbox email', async () => {
        await runToNextAction(member().toLowerCase())
        const [delivered] = world.ses.delivered
        expect(delivered.to).toEqual([{ name: '', address: member() }])

        await unsubscribeThroughLink(delivered)

        expect(await ordinaryEmailSkipReason(member())).toBe('opted_out')
    })

    it.each<[string, (writtenAs: string) => string]>([
        ['as the step wrote it', (writtenAs) => writtenAs],
        ['trimmed', (writtenAs) => writtenAs.trim()],
        ['as the member stored it', () => member()],
        ['lowercased', (writtenAs) => writtenAs.trim().toLowerCase()],
    ])('skips a sandbox email to someone who unsubscribed with the address %s', async (_spelling, spell) => {
        const writtenAs = `  ${member().toUpperCase()} `
        await world.recipients.optOut(world.team.id, [spell(writtenAs)])

        const { finished } = await runToNextAction(writtenAs)

        expect(world.ses.attempts).toBe(0)
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'skipped', reason: 'opted_out' })
    })

    describe('when the delivered address cannot be read', () => {
        let blackhole: Server
        let stalledPostgres: PostgresRouter
        const heldSockets = new Set<Socket>()

        beforeAll(async () => {
            blackhole = createServer((socket) => heldSockets.add(socket))
            await new Promise<void>((resolve) => blackhole.listen(0, '127.0.0.1', resolve))
            const { port } = blackhole.address() as AddressInfo
            stalledPostgres = new PostgresRouter({
                ...defaultConfig,
                DATABASE_URL: `postgres://posthog:posthog@127.0.0.1:${port}/posthog`,
            })
        })

        afterAll(async () => {
            heldSockets.forEach((socket) => socket.destroy())
            await new Promise((resolve) => blackhole.close(resolve))
            await stalledPostgres.end()
        })

        it('retries the step without an SES attempt and sends it with an unsubscribe link once the read answers', async () => {
            const stalledExecutor = buildExecutor(caps, deliveredAddressReader(stalledPostgres, 100))
            const routed = await stalledExecutor.execute(runFor(member().toLowerCase()))

            const stalled = await stalledExecutor.execute(nextDequeue(routed.invocation))

            expect(world.ses.attempts).toBe(0)
            expect(stalled.invocation.queue).toBe('emailsandbox')
            expect(stalled.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(Date.now())

            await runSandboxQueue(buildExecutor(), stalled.invocation)
            expect(world.ses.delivered).toHaveLength(1)
            await unsubscribeThroughLink(world.ses.delivered[0])
            expect(await ordinaryEmailSkipReason(member())).toBe('opted_out')
        })
    })

    it("delivers a marketing email until the person reaches the team's frequency cap, then skips the next one", async () => {
        await world.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO workflows_teamworkflowsconfig
                (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                 email_sending_suspension_reason, marketing_frequency_cap_max_messages,
                 marketing_frequency_cap_window_days)
             VALUES ($1, false, 'off', '', 1, 7)`,
            [world.team.id],
            'test:cap-one-marketing-email-a-week'
        )
        const roomy = { dailyCaps: { team: 100, recipient: 100 } }

        const first = await runToNextAction(member(), roomy)
        const second = await runToNextAction(member(), roomy)

        expect(world.ses.delivered).toHaveLength(1)
        expect([first, second].map(({ finished }) => finished.invocation.state.variables?.email_result)).toEqual([
            { status: 'accepted', message_id: 'ses-1' },
            { status: 'skipped', reason: 'frequency_capped' },
        ])
    })

    it('logs why the template failed to render', async () => {
        const action = hogFlow.actions.find((candidate) => candidate.id === 'email')!
        ;(action.config as any).inputs.email.value.subject = '{{ person.properties.missing }}'

        const { segments } = await runToNextAction(member())

        expect(segments[0].logs.map(({ level, message }) => [level, message])).toContainEqual([
            'error',
            expect.stringContaining('failed to render: The rendered sandbox email is missing a recipient, subject'),
        ])
    })

    it('backs off on the sandbox queue from 30 seconds up to 15 minutes between retries', async () => {
        const now = DateTime.utc()
        const clock = jest.spyOn(Date, 'now').mockReturnValue(now.toMillis())
        world.ses.replyAlways({ kind: 'drop' })

        const { segments } = await runToNextAction(member(), { dailyCaps: { team: 100, recipient: 100 } }).finally(() =>
            clock.mockRestore()
        )
        const delaysMs = segments
            .slice(0, -1)
            .map((segment) => segment.invocation.queueScheduledAt!.toMillis() - now.toMillis())

        expect(delaysMs).toHaveLength(MAX_SANDBOX_RETRIES)
        expect(delaysMs[0]).toBeGreaterThanOrEqual(24_000)
        expect(delaysMs[0]).toBeLessThanOrEqual(30_000)
        expect(Math.max(...delaysMs)).toBeLessThanOrEqual(15 * 60_000)
        expect(segments.slice(0, -1).every((segment) => segment.invocation.queue === 'emailsandbox')).toBe(true)
    })
})
