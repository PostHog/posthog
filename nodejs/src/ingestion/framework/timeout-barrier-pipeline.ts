import { BatchBudget } from './batch-budget'
import { recordBudgetCheckpoint } from './metrics'
import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult, timeout } from './results'

/** Names the barrier in the reasons it produces and in the checkpoint counter. */
const TIMEOUT_BARRIER = 'timeoutBarrier'

/**
 * The last point at which a batch budget can stop an element. An element that
 * reaches the barrier with time left carries an unlimited budget from here on,
 * so every later checkpoint is a no-op and the element is guaranteed to finish
 * its remaining chain; one that reaches the barrier exhausted is cut here.
 *
 * Put the barrier before the first step whose side effects make finishing
 * cheaper than cutting: a write that a redelivery would otherwise repeat or
 * have to reconcile. The trade is a longer tail past the deadline, because a
 * batch that runs out of time still finishes every element already past the
 * barrier.
 *
 * Swapping the budget is a context rewrite, which a step cannot do — hence a
 * framework stage rather than a step.
 */
export class TimeoutBarrierPipeline<TInput, TOutput, C, R extends string = never>
    implements Pipeline<TInput, TOutput, C, R>
{
    constructor(private previousPipeline: Pipeline<TInput, TOutput, C, R>) {}

    async process(input: OkResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C, R>> {
        const previousResultWithContext = await this.previousPipeline.process(input)

        const budget = previousResultWithContext.context.budget
        if (!isOkResult(previousResultWithContext.result) || budget === undefined) {
            return previousResultWithContext
        }
        if (budget.exhausted) {
            recordBudgetCheckpoint('step', TIMEOUT_BARRIER)
            return {
                result: timeout(`budget exceeded before ${TIMEOUT_BARRIER}`),
                context: previousResultWithContext.context,
            }
        }
        // The unlimited budget is one shared instance, so a batch with no time
        // policy crosses the barrier without rebuilding a context.
        if (budget === BatchBudget.unlimited()) {
            return previousResultWithContext
        }
        return {
            result: previousResultWithContext.result,
            context: { ...previousResultWithContext.context, budget: BatchBudget.unlimited() },
        }
    }
}
