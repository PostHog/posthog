import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../../../types'
import { HogInputsService } from '../../hog-inputs.service'
import { HogFlowExecutorService } from '../../hogflows/hogflow-executor.service'
import { RecipientTokensService } from '../recipient-tokens.service'
import { SES_REJECTED, SES_THROTTLE, SesReply } from './_tests/fake-ses-endpoint'
import { useSandboxWorld } from './_tests/sandbox-world'
import { claimSandboxCaps } from './sandbox-caps'
import { SandboxEventProperties, SandboxTerminalOutcome } from './sandbox-email-events'
import { MAX_SANDBOX_RETRIES, SandboxEmailSendStep } from './sandbox-email-step'

type RecordedEvent = { teamId: number; outcome: SandboxTerminalOutcome; properties: SandboxEventProperties }

describe('SandboxEmailSendStep', () => {
    const world = useSandboxWorld()
    const tokens = new RecipientTokensService('00beef0000beef0000beef0000beef00', 'http://localhost:8000')
    const caps = { team: 5, recipient: 1 }
    let hogFlow: HogFlow
    let events: RecordedEvent[]

    const member = () => `Member-${world.team.id}@Example.com`

    beforeEach(async () => {
        await world.addMember(member())
        events = []
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

    const buildExecutor = (dailyCaps = caps): HogFlowExecutorService => {
        const step = new SandboxEmailSendStep({
            service: world.service({ caps: dailyCaps }),
            hogInputsService: new HogInputsService({} as any, tokens, {} as any),
            siteUrl: 'http://localhost:8000',
            recipientPreferences: { checkMarketingFrequencyCap: () => Promise.resolve({ capped: false }) },
            events: {
                capture: (teamId, outcome, properties) => {
                    events.push({ teamId, outcome, properties })
                    return Promise.resolve()
                },
            },
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
        expect(events).toEqual([
            {
                teamId: world.team.id,
                outcome: 'accepted',
                properties: { workflow_id: hogFlow.id, action_id: 'email', is_test: false },
            },
        ])

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
            expect(metricNames(segments)).toEqual([[metric, 'email']])
            expect(finished.invocation.state.currentAction?.id).toBe('wait')
            expect(finished.invocation.state.variables?.email_result).toEqual(stepResult)
        }
    )

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

    it('honours an unsubscribe from a sandbox email when later emails spell the address differently', async () => {
        const roomy = { dailyCaps: { team: 100, recipient: 100 } }
        await runToNextAction(member().toUpperCase(), roomy)
        const [first] = world.ses.delivered
        const token = new URL(first.text!.match(/https?:\/\/\S+/)![0]).pathname.split('/').filter(Boolean).at(-1)!
        const unsubscribed = tokens.validatePreferencesToken(token)
        expect(unsubscribed.valid).toBe(true)
        await world.recipients.optOut(world.team.id, [(unsubscribed as { identifier: string }).identifier])

        const { finished } = await runToNextAction(member().toLowerCase(), roomy)

        expect(world.ses.delivered).toHaveLength(1)
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'skipped', reason: 'opted_out' })
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
