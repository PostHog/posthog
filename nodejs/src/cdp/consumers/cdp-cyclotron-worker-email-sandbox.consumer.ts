import { DateTime } from 'luxon'

import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

export class CdpCyclotronWorkerEmailSandbox extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmailSandbox'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'emailsandbox'
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const { loadedInvocations, canceledResults } = await this.loadHogFlows(invocations)
        const results = await Promise.all(
            loadedInvocations.map((invocation) =>
                isStillOnSandboxEmailStep(invocation)
                    ? this.hogFlowExecutor.execute(invocation)
                    : Promise.resolve(routeBackToHogFlowQueue(invocation))
            )
        )
        return [...canceledResults, ...results]
    }
}

function isStillOnSandboxEmailStep(invocation: CyclotronJobInvocationHogFlow): boolean {
    const currentActionId = invocation.state?.currentAction?.id
    return invocation.hogFlow.actions.some((action) => action.id === currentActionId && action.type === 'email_sandbox')
}

function routeBackToHogFlowQueue(
    invocation: CyclotronJobInvocationHogFlow
): CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> {
    const result = createInvocationResult<CyclotronJobInvocationHogFlow>(
        invocation,
        { queue: 'hogflow', queuePriority: invocation.queuePriority, queueScheduledAt: DateTime.now() },
        { finished: false }
    )
    if (result.invocation.state?.currentAction) {
        result.invocation.state.currentAction.routingOnlyReschedule = true
    }
    return result
}
