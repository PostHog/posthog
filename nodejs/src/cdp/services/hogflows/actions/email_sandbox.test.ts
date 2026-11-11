import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronJobInvocationHogFlow, HogFlowInvocationContext } from '../../../types'
import { HogExecutorExecuteAsyncOptions } from '../../hog-executor-async.service'
import { HogFlowExecutorService } from '../hogflow-executor.service'
import { SandboxEmailSendDecision, SandboxEmailStep, SandboxEmailTestClient } from './email_sandbox'

describe('SandboxEmailActionHandler', () => {
    const now = DateTime.fromISO('2026-01-01T00:00:00.000Z', { zone: 'UTC' })
    let hogFlow: HogFlow

    beforeEach(() => {
        jest.spyOn(Date, 'now').mockReturnValue(now.toMillis())
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
                                    value: { to: { email: 'member@example.com' }, subject: 'Hi', text: 'Hello' },
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

    const buildExecutor = (sandboxEmail: {
        enabled: boolean
        send?: SandboxEmailStep | null
        testClient?: SandboxEmailTestClient | null
    }): HogFlowExecutorService =>
        new HogFlowExecutorService({} as any, {} as any, {} as any, {} as any, {} as any, null, undefined, undefined, {
            sandboxEmail,
        })

    type DeliveredEmail = { to: string; subject: string }

    class FakeMailbox implements SandboxEmailStep {
        readonly delivered: DeliveredEmail[] = []

        send({ action }: Parameters<SandboxEmailStep['send']>[0]): Promise<SandboxEmailSendDecision> {
            const { to, subject } = action.config.inputs.email.value
            this.delivered.push({ to: to.email, subject })
            return Promise.resolve({ outcome: 'accepted', messageId: `message-${this.delivered.length}` })
        }
    }

    const fakeSend = (decision: SandboxEmailSendDecision): SandboxEmailStep => ({
        send: () => Promise.resolve(decision),
    })

    const memberEmail: DeliveredEmail = { to: 'member@example.com', subject: 'Hi' }

    const jobOnEmailStep = (
        queue: CyclotronJobInvocationHogFlow['queue'],
        currentAction: Partial<NonNullable<HogFlowInvocationContext['currentAction']>> = {}
    ): CyclotronJobInvocationHogFlow => {
        const invocation = createExampleHogFlowInvocation(hogFlow, {
            flowVersion: 1,
            currentAction: { id: 'email', startedAtTimestamp: now.toMillis(), ...currentAction },
        })
        invocation.queue = queue
        invocation.queuePriority = 1
        return invocation
    }

    const nextDequeue = (invocation: CyclotronJobInvocationHogFlow): CyclotronJobInvocationHogFlow => ({
        ...invocation,
        state: parseJSON(JSON.stringify(invocation.state)),
        queueScheduledAt: undefined,
    })

    it('sends on the sandbox queue and runs the next action only after the hogflow queue takes the job back', async () => {
        const mailbox = new FakeMailbox()
        const executor = buildExecutor({ enabled: true, send: mailbox })

        const routed = await executor.execute(jobOnEmailStep('hogflow'))
        expect(mailbox.delivered).toEqual([])
        expect(routed.invocation.queue).toBe('emailsandbox')
        expect(routed.invocation.queueScheduledAt?.toMillis()).toBe(now.toMillis())
        expect(routed.invocation.state.currentAction).toMatchObject({ id: 'email', routingOnlyReschedule: true })

        const handedBack = await executor.execute(nextDequeue(routed.invocation))
        expect(mailbox.delivered).toEqual([memberEmail])
        expect(handedBack.finished).toBe(false)
        expect(handedBack.invocation.queue).toBe('hogflow')
        expect(handedBack.invocation.queueScheduledAt?.toMillis()).toBe(now.toMillis())
        expect(handedBack.invocation.state.currentAction).toMatchObject({
            id: 'email',
            sandboxEmail: { outcome: 'accepted', messageId: 'message-1' },
        })
        expect(handedBack.invocation.state.flowVersion).toBe(3)

        const finished = await executor.execute(nextDequeue(handedBack.invocation))
        expect(mailbox.delivered).toEqual([memberEmail])
        expect(finished.invocation.state.currentAction?.id).toBe('wait')
        expect(finished.invocation.state.variables?.email_result).toEqual({
            status: 'accepted',
            message_id: 'message-1',
        })
    })

    it.each([
        ['the hogflow queue keeps its priority', 'hogflow', 1, undefined, 1],
        ['the email queue restores the priority it stashed', 'email', 0, { originPriority: 2 }, 2],
    ] as const)('routes to the sandbox queue: %s', async (_name, queue, queuePriority, queueMetadata, expected) => {
        const invocation = jobOnEmailStep(queue)
        invocation.queuePriority = queuePriority
        invocation.queueMetadata = queueMetadata

        const result = await buildExecutor({ enabled: true }).executeCurrentAction(invocation)

        expect(result.invocation).toMatchObject({
            queue: 'emailsandbox',
            queuePriority: expected,
            queueParameters: null,
            queueMetadata: undefined,
        })
    })

    it('keeps a retry on the sandbox queue until the send step decides', async () => {
        const retryAt = now.plus({ seconds: 30 })
        const result = await buildExecutor({ enabled: true, send: fakeSend({ retryAt }) }).execute(
            jobOnEmailStep('emailsandbox')
        )

        expect(result.invocation.queue).toBe('emailsandbox')
        expect(result.invocation.queueScheduledAt?.toMillis()).toBe(retryAt.toMillis())
        expect(result.invocation.state.currentAction?.sandboxEmail).toBeUndefined()
    })

    it.each([
        ['sending is off', false, true, 'skipped', 'sending_disabled'],
        ['the worker has no send step', true, false, 'failed', 'sandbox_worker_unavailable'],
    ])('hands the job back without sending when %s', async (_name, enabled, withSendStep, outcome, reason) => {
        const mailbox = new FakeMailbox()

        const result = await buildExecutor({ enabled, send: withSendStep ? mailbox : null }).execute(
            jobOnEmailStep('emailsandbox')
        )

        expect(mailbox.delivered).toEqual([])

        expect(result.invocation.queue).toBe('hogflow')
        expect(result.invocation.state.currentAction).toMatchObject({ id: 'email', sandboxEmail: { outcome, reason } })
    })

    it('skips the step and continues on the hogflow queue when sending is off', async () => {
        const result = await buildExecutor({ enabled: false }).execute(jobOnEmailStep('hogflow'))

        expect(result.invocation.queue).toBe('hogflow')
        expect(result.invocation.state.currentAction?.id).toBe('wait')
        expect(result.invocation.state.variables?.email_result).toEqual({
            status: 'skipped',
            reason: 'sending_disabled',
        })
    })

    it.each([
        ['abort', true, 'email'],
        ['continue', false, 'wait'],
    ] as const)('finishes a failed send by on_error %s', async (onError, expectedFinished, expectedActionId) => {
        hogFlow.actions.find((action) => action.id === 'email')!.on_error = onError

        const result = await buildExecutor({ enabled: true }).executeCurrentAction(
            jobOnEmailStep('hogflow', { sandboxEmail: { outcome: 'failed', reason: 'ses_rejected' } })
        )

        expect(result.error).toBe('Sandbox email was not sent: ses_rejected')
        expect(result.finished).toBe(expectedFinished)
        expect(result.invocation.state.currentAction?.id).toBe(expectedActionId)
    })

    it.each([
        ['abort', true, 'email', 'smtp down'],
        ['continue', false, 'wait', undefined],
    ] as const)(
        'fails the job only by on_error %s when the send step throws on the sandbox queue',
        async (onError, expectedFinished, expectedActionId, expectedError) => {
            hogFlow.actions.find((action) => action.id === 'email')!.on_error = onError
            const send: SandboxEmailStep = { send: () => Promise.reject(new Error('smtp down')) }

            const result = await buildExecutor({ enabled: true, send }).execute(jobOnEmailStep('emailsandbox'))

            expect(result.error).toBe(expectedError)
            expect(result.finished).toBe(expectedFinished)
            expect(result.invocation.state.currentAction?.id).toBe(expectedActionId)
        }
    )

    it.each<[string, HogExecutorExecuteAsyncOptions, SandboxEmailTestClient | null, object, string | undefined]>([
        [
            'a mocked test reports a send without calling out',
            { isTest: true, functions: {} },
            null,
            { status: 'accepted' },
            undefined,
        ],
        [
            'a real test without a test client fails',
            { isTest: true },
            null,
            { status: 'failed', reason: 'sandbox_worker_unavailable' },
            'Sandbox email was not sent: sandbox_worker_unavailable',
        ],
        [
            'a real test reports what the sandbox worker answered',
            { isTest: true },
            { send: () => Promise.resolve({ status: 'pending', reason: 'pause_state_unavailable' }) },
            { status: 'pending', reason: 'pause_state_unavailable' },
            undefined,
        ],
    ])('runs a test inline: %s', async (_name, hogExecutorOptions, testClient, execResult, error) => {
        const mailbox = new FakeMailbox()

        const result = await buildExecutor({ enabled: true, send: mailbox, testClient }).executeCurrentAction(
            jobOnEmailStep('hogflow'),
            { hogExecutorOptions }
        )

        expect(mailbox.delivered).toEqual([])

        expect(result.invocation.queue).toBe('hogflow')
        expect(result.execResult).toEqual(execResult)
        expect(result.error).toEqual(error)
    })
})
