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
import { MAX_SANDBOX_RETRIES, SandboxEmailSendStep } from './sandbox-email-step'
import { SandboxEmailService, SandboxEmailServiceDeps } from './sandbox-email.service'

describe('SandboxEmailSendStep', () => {
    const now = DateTime.fromISO('2026-01-01T00:00:00.000Z', { zone: 'UTC' })
    let hogFlow: HogFlow
    let ses: jest.Mocked<SandboxEmailServiceDeps['ses']>
    let capture: jest.Mock
    let serviceOverrides: Partial<SandboxEmailServiceDeps>

    beforeEach(() => {
        jest.spyOn(Date, 'now').mockReturnValue(now.toMillis())
        ses = { send: jest.fn().mockResolvedValue({ status: 'accepted', messageId: 'ses-1' }) }
        capture = jest.fn().mockResolvedValue(undefined)
        serviceOverrides = {}
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
                                        text: 'Hello',
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
        hogFlow.version = 3
    })

    const buildExecutor = (): HogFlowExecutorService => {
        const service = new SandboxEmailService({
            enabled: true,
            fromAddress: 'sandbox@send.example.com',
            tenantName: 'sandbox-tenant',
            isProvisioned: () => Promise.resolve(true),
            checkRecipient: () => Promise.resolve({ ok: true }),
            authorize: () =>
                Promise.resolve({
                    ok: true,
                    organizationId: 'org-1',
                    organizationName: 'Acme',
                    storedAddress: 'member@example.com',
                    tenant: { sendingStatus: 'ENABLED', syncedAt: now.toJSDate() },
                }),
            claimCaps: () => Promise.resolve({ ok: true }),
            ses,
            now: () => now.toJSDate(),
            ...serviceOverrides,
        })
        const step = new SandboxEmailSendStep({
            service,
            hogInputsService: new HogInputsService(
                {} as any,
                new RecipientTokensService('00beef0000beef0000beef0000beef00', 'http://localhost:8000'),
                {} as any
            ),
            siteUrl: 'http://localhost:8000',
            recipientPreferences: { checkMarketingFrequencyCap: () => Promise.resolve({ capped: false }) },
            events: { capture },
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
            {
                sandboxEmail: { enabled: true, send: step },
            }
        )
    }

    const runOnHogflowQueue = (): CyclotronJobInvocationHogFlow => {
        const invocation = createExampleHogFlowInvocation(
            hogFlow,
            { currentAction: { id: 'email', startedAtTimestamp: now.toMillis() } },
            { properties: { email: 'member@example.com', name: 'Mem' } }
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
        routed: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>[]> => {
        const segments = [await executor.execute(nextDequeue(routed))]
        while (segments.at(-1)!.invocation.queue === 'emailsandbox') {
            segments.push(await executor.execute(nextDequeue(segments.at(-1)!.invocation)))
        }
        return segments
    }

    it('renders and sends on the sandbox queue, then the hogflow queue runs the next action', async () => {
        const executor = buildExecutor()
        const batchRun = runOnHogflowQueue()
        batchRun.parentRunId = 'batch-run-1'

        const routed = await executor.execute(batchRun)
        expect(ses.send).not.toHaveBeenCalled()
        expect(routed.invocation.queue).toBe('emailsandbox')

        const [sent] = await runSandboxQueue(executor, routed.invocation)
        expect(ses.send).toHaveBeenCalledTimes(1)
        const [message, tags] = ses.send.mock.calls[0]
        expect(message).toMatchObject({ to: { address: 'member@example.com' }, subject: 'Hi Mem' })
        expect(tags).toEqual({
            teamId: hogFlow.team_id,
            hogFlowId: hogFlow.id,
            invocationId: routed.invocation.id,
            actionId: 'email',
            flowVersion: 3,
            isTest: false,
            parentRunId: 'batch-run-1',
        })
        expect(sent.invocation.queue).toBe('hogflow')
        expect(sent.invocation.state.currentAction?.id).toBe('email')
        expect(sent.metrics.map((metric) => [metric.metric_name, metric.instance_id])).toEqual([
            ['email_sandbox_sent', 'email'],
        ])
        expect(capture).toHaveBeenCalledWith(hogFlow.team_id, 'accepted', {
            workflow_id: hogFlow.id,
            action_id: 'email',
            is_test: false,
        })

        const finished = await executor.execute(nextDequeue(sent.invocation))
        expect(ses.send).toHaveBeenCalledTimes(1)
        expect(finished.invocation.state.currentAction?.id).toBe('wait')
        expect(finished.invocation.state.variables?.email_result).toEqual({ status: 'accepted', message_id: 'ses-1' })
    })

    it.each([
        [
            'SES rejects the message',
            (): void => void ses.send.mockResolvedValue({ status: 'failed', reason: 'ses_rejected' }),
            { status: 'failed', reason: 'ses_rejected' },
            'email_sandbox_failed',
            1,
        ],
        [
            'SES throttles every attempt',
            (): void => void ses.send.mockResolvedValue({ status: 'retry', reason: 'ses_throttled' }),
            { status: 'failed', reason: 'retries_exhausted' },
            'email_sandbox_failed',
            MAX_SANDBOX_RETRIES + 1,
        ],
        [
            'the template renders no subject',
            (): void => {
                const action = hogFlow.actions.find((candidate) => candidate.id === 'email')!
                ;(action.config as any).inputs.email.value.subject = '{{ person.properties.missing }}'
            },
            { status: 'failed', reason: 'render_failed' },
            'email_sandbox_failed',
            0,
        ],
        [
            'a daily cap is reached',
            (): void => {
                serviceOverrides.claimCaps = () => Promise.resolve({ ok: false, reason: 'daily_cap_reached' })
            },
            { status: 'skipped', reason: 'daily_cap_reached' },
            'email_sandbox_blocked',
            0,
        ],
        [
            'SES throttles once while one daily cap token is left',
            (): void => {
                let tokens = 1
                serviceOverrides.claimCaps = () =>
                    Promise.resolve(tokens-- > 0 ? { ok: true } : { ok: false, reason: 'daily_cap_reached' })
                ses.send.mockResolvedValueOnce({ status: 'retry', reason: 'ses_throttled' })
            },
            { status: 'accepted', message_id: 'ses-1' },
            'email_sandbox_sent',
            2,
        ],
        [
            'SES may have accepted a send before failing transiently, with one daily cap token left',
            (): void => {
                let tokens = 1
                serviceOverrides.claimCaps = () =>
                    Promise.resolve(tokens-- > 0 ? { ok: true } : { ok: false, reason: 'daily_cap_reached' })
                ses.send.mockResolvedValueOnce({ status: 'retry', reason: 'ses_transient' })
            },
            { status: 'skipped', reason: 'daily_cap_reached' },
            'email_sandbox_blocked',
            1,
        ],
    ])('stores the outcome when %s and continues past it', async (_name, arrange, stepResult, metric, sesCalls) => {
        arrange()
        const executor = buildExecutor()

        const routed = await executor.execute(runOnHogflowQueue())
        const segments = await runSandboxQueue(executor, routed.invocation)
        const handedBack = segments.at(-1)!
        const finished = await executor.execute(nextDequeue(handedBack.invocation))

        expect(ses.send).toHaveBeenCalledTimes(sesCalls)
        expect(segments.flatMap((segment) => segment.metrics.map((m) => m.metric_name))).toEqual([metric])
        expect(handedBack.invocation.queue).toBe('hogflow')
        expect(finished.invocation.state.currentAction?.id).toBe('wait')
        expect(finished.invocation.state.variables?.email_result).toEqual(stepResult)
    })

    it('logs why the template failed to render', async () => {
        const action = hogFlow.actions.find((candidate) => candidate.id === 'email')!
        ;(action.config as any).inputs.email.value.subject = '{{ person.properties.missing }}'
        const executor = buildExecutor()

        const routed = await executor.execute(runOnHogflowQueue())
        const [rendered] = await runSandboxQueue(executor, routed.invocation)

        expect(rendered.logs.map(({ level, message }) => [level, message])).toContainEqual([
            'error',
            expect.stringContaining('failed to render: The rendered sandbox email is missing a recipient, subject'),
        ])
    })

    it('backs off on the sandbox queue from 30 seconds up to 15 minutes between retries', async () => {
        ses.send.mockResolvedValue({ status: 'retry', reason: 'ses_transient' })
        const executor = buildExecutor()

        const routed = await executor.execute(runOnHogflowQueue())
        const segments = await runSandboxQueue(executor, routed.invocation)
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
