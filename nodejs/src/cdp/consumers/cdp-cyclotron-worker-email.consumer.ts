import { v7 as uuidv7 } from 'uuid'

import { CyclotronInvocationQueueParametersEmailCaptureType } from '~/cdp/schema/cyclotron'
import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'email'
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const captureJobs = invocations.filter((invocation) => invocation.queueParameters?.type === 'emailCapture')
        const sendJobs = invocations.filter((invocation) => invocation.queueParameters?.type !== 'emailCapture')
        const captures = await Promise.all(
            captureJobs.map((invocation) => this.emailService.executeConversationCapture(invocation))
        )
        const sends = sendJobs.length ? await super.processInvocations(sendJobs) : []
        return [...captures, ...sends]
    }

    protected override async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        const captureJobs: (CyclotronJobInvocation & {
            queueParameters: CyclotronInvocationQueueParametersEmailCaptureType
        })[] = results.flatMap((result) =>
            (result.conversationCaptures ?? []).map((capture) => ({
                id: uuidv7(),
                teamId: result.invocation.teamId,
                functionId: result.invocation.functionId,
                parentRunId: result.invocation.parentRunId,
                state: null,
                queue: 'email' as const,
                queuePriority: result.invocation.queuePriority,
                queueParameters: { type: 'emailCapture' as const, capture, attempts: 0 },
            }))
        )
        if (captureJobs.length) {
            try {
                await this.cyclotronJobQueue.queueInvocations(captureJobs)
            } catch {
                void Promise.allSettled(
                    captureJobs.map((job) =>
                        this.emailService.recordConversationCaptureSkipped(
                            job.teamId,
                            job.queueParameters.capture.source_id,
                            'queue_unavailable'
                        )
                    )
                )
            }
        }
        await super.queueInvocationResults(results)
    }
}
