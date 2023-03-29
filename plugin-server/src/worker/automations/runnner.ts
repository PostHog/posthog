import { EnqueuedAutomationJob } from 'types'

import { runInSpan } from '../../sentry'
import { Hub } from '../../types'
import { DependencyUnavailableError } from '../../utils/db/error'
import { timeoutGuard } from '../../utils/db/utils'

// Only used in tests
// TODO: update to test for side-effects of running the pipeline rather than
// this return type.
export type AutomationRunnerResult = {
    lastStep: string
    args: any[]
    error?: string
}

class StepError extends Error {
    step: string
    args: any[]
    constructor(step: string, args: any[], message: string) {
        super(message)
        this.step = step
        this.args = args
    }
}

export class AutomationRunner {
    constructor(private hub: Hub, private event: EnqueuedAutomationJob) {}

    async runAutomationJob(): Promise<AutomationRunnerResult | null> {
        // this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'event' })

        try {
            let result: AutomationRunnerResult | null = null

            // TODO: Determine current state of the event
            // Try and run the state in question
            // Queue the follow up actions

            // this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')

            //

            return result
        } catch (error) {
            if (error instanceof DependencyUnavailableError) {
                // If this is an error with a dependency that we control, we want to
                // ensure that the caller knows that the event was not processed,
                // for a reason that we control and that is transient.
                throw error
            }

            return { lastStep: error.step, args: [], error: error.message }
        }
    }

    protected runStep<Step extends (...args: any[]) => any>(
        step: Step,
        args: Parameters<Step>,
        sentToDql = true
    ): ReturnType<Step> {
        const timer = new Date()

        return runInSpan(
            {
                op: 'runStep',
                description: step.name,
            },
            async () => {
                const timeout = timeoutGuard('Automation step stalled. Timeout warning after 30 sec!', {
                    step: step.name,
                    event: JSON.stringify(this.event),
                })
                try {
                    const result = await step(...args)
                    // this.hub.statsd?.increment('kafka_queue.event_pipeline.step', { step: step.name })
                    // this.hub.statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: step.name })
                    return result
                } catch (err) {
                    await this.handleError(err, step.name, args, sentToDql)
                } finally {
                    clearTimeout(timeout)
                }
            }
        )
    }

    private async handleError(err: any, currentStepName: string, currentArgs: any, sentToDql: boolean) {
        // Capture the error event and stop the task
        // const serializedArgs = currentArgs.map((arg: any) => this.serialize(arg))
        // status.error('🔔', 'step_failed', { currentStepName, err })
        // Sentry.captureException(err, { extra: { currentStepName, serializedArgs, originalEvent: this.event } })
        // this.hub.statsd?.increment('kafka_queue.event_pipeline.step.error', { step: currentStepName })

        // if (err instanceof DependencyUnavailableError) {
        //     // If this is an error with a dependency that we control, we want to
        //     // ensure that the caller knows that the event was not processed,
        //     // for a reason that we control and that is transient.
        //     throw err
        // }

        // if (sentToDql) {
        //     try {
        //         const message = generateEventDeadLetterQueueMessage(this.event, err)
        //         await this.hub.db.kafkaProducer!.queueMessage(message)
        //         this.hub.statsd?.increment('events_added_to_dead_letter_queue')
        //     } catch (dlqError) {
        //         status.info('🔔', `Errored trying to add event to dead letter queue. Error: ${dlqError}`)
        //         Sentry.captureException(dlqError, {
        //             extra: { currentStepName, serializedArgs, originalEvent: this.event, err },
        //         })
        //     }
        // }

        throw new StepError(currentStepName, currentArgs, err.message)
    }
}
