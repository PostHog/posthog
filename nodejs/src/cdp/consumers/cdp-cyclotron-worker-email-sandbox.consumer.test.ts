import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createHogFlowInvocationContext, insertHogFlow } from '../_tests/fixtures-hogflows'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, HogFlowInvocationContext } from '../types'
import { CdpCyclotronWorkerEmailSandbox } from './cdp-cyclotron-worker-email-sandbox.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

jest.setTimeout(10000)

describe('CdpCyclotronWorkerEmailSandbox', () => {
    let hub: Hub
    let hogFlow: HogFlow

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    const insertSandboxFlow = async (teamId: number, emailFields: Partial<HogFlowAction> = {}): Promise<HogFlow> =>
        insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(teamId)
                .withStatus('active')
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        email: {
                            ...emailFields,
                            type: 'email_sandbox',
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
        )

    beforeEach(async () => {
        const { team } = await createTestTeamFixture(hub.postgres)
        hogFlow = await insertSandboxFlow(team.id)
    })

    const jobAt = (currentActionId: string): CyclotronJobInvocation => ({
        id: new UUIDT().toString(),
        teamId: hogFlow.team_id,
        functionId: hogFlow.id,
        queue: 'emailsandbox',
        queuePriority: 1,
        state: createHogFlowInvocationContext({
            event: { distinct_id: 'distinct_A_1', properties: {} } as any,
            currentAction: { id: currentActionId, startedAtTimestamp: Date.now() },
        }),
    })

    const currentAction = (result: CyclotronJobInvocationResult): HogFlowInvocationContext['currentAction'] =>
        (result.invocation.state as HogFlowInvocationContext).currentAction

    it('hands a sandbox step back to the hogflow queue, which then runs the next action', async () => {
        const sandboxWorker = new CdpCyclotronWorkerEmailSandbox(hub, createCdpConsumerDeps(hub), createMockJobQueue())

        const [handedBack] = await sandboxWorker.processInvocations([jobAt('email')])

        expect(handedBack.finished).toBe(false)
        expect(handedBack.invocation.queue).toBe('hogflow')
        expect(currentAction(handedBack)).toMatchObject({
            id: 'email',
            sandboxEmail: { outcome: 'skipped', reason: 'sending_disabled' },
        })

        const hogflowWorker = new CdpCyclotronWorkerHogFlow(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        const [finished] = await hogflowWorker.processInvocations([
            { ...handedBack.invocation, state: parseJSON(JSON.stringify(handedBack.invocation.state)) },
        ])

        expect(currentAction(finished)?.id).toBe('wait')
    })

    it('hands a step whose filter stopped matching back to the hogflow queue before the next action runs', async () => {
        hogFlow = await insertSandboxFlow(hogFlow.team_id, {
            filters: {
                properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }],
                bytecode: ['_H', 1, 30],
            },
        } as Partial<HogFlowAction>)
        const sandboxWorker = new CdpCyclotronWorkerEmailSandbox(hub, createCdpConsumerDeps(hub), createMockJobQueue())

        const [result] = await sandboxWorker.processInvocations([jobAt('email')])

        expect(result.finished).toBe(false)
        expect(result.invocation.queue).toBe('hogflow')
        expect(result.invocation.queueScheduledAt!.toMillis()).toBeLessThanOrEqual(Date.now())
        expect(currentAction(result)?.id).toBe('wait')
        expect(result.logs.map((log) => log.message)).not.toContainEqual(expect.stringContaining('Executing action'))
    })

    it('routes a job whose step is no longer a sandbox email back to the hogflow queue without running it', async () => {
        const sandboxWorker = new CdpCyclotronWorkerEmailSandbox(hub, createCdpConsumerDeps(hub), createMockJobQueue())

        const [result] = await sandboxWorker.processInvocations([jobAt('wait')])

        expect(result.finished).toBe(false)
        expect(result.invocation.queue).toBe('hogflow')
        expect(result.invocation.queueScheduledAt).toBeDefined()
        expect(currentAction(result)).toMatchObject({ id: 'wait', routingOnlyReschedule: true })
        expect(result.logs).toEqual([])
    })
})
