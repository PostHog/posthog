import { BatchBudget } from './batch-budget'
import { recordBudgetCheckpoint } from './metrics'
import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult, timeout } from './results'

const TIMEOUT_BARRIER = 'timeoutBarrier'

/**
 * The last budget checkpoint. An element that reaches it with time left
 * continues with an unlimited budget, so it always finishes; an exhausted one
 * is cut here. It is a stage, not a step, because it rewrites the context.
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
        if (budget === BatchBudget.unlimited()) {
            return previousResultWithContext
        }
        return {
            result: previousResultWithContext.result,
            context: { ...previousResultWithContext.context, budget: BatchBudget.unlimited() },
        }
    }
}
