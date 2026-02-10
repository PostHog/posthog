import { instrumentFn } from '../../common/tracing/tracing-utils'
import { TopHogMetricType, type TopHogPipeOptions } from '../tophog/tophog'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, isOkResult } from './results'
import { ProcessingStep } from './steps'

export class StepPipeline<TInput, TIntermediate, TOutput, C> implements Pipeline<TInput, TOutput, C> {
    private stepName: string

    constructor(
        private currentStep: (value: TIntermediate) => Promise<PipelineResult<TOutput>>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C>,
        private topHogOptions?: TopHogPipeOptions<TIntermediate>
    ) {
        this.stepName = currentStep.name || 'anonymousStep'
    }

    pipe<U>(
        step: ProcessingStep<TOutput, U>,
        options?: { topHog?: TopHogPipeOptions<TOutput> }
    ): StepPipeline<TInput, TOutput, U, C> {
        return new StepPipeline<TInput, TOutput, U, C>(step, this, options?.topHog)
    }

    async process(input: PipelineResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C>> {
        const previousResultWithContext = await this.previousPipeline.process(input)

        const previousResult = previousResultWithContext.result
        if (!isOkResult(previousResult)) {
            return {
                result: previousResult,
                context: previousResultWithContext.context,
            }
        }

        const startTime = this.topHogOptions?.length ? performance.now() : 0

        const currentResult = await instrumentFn({ key: this.stepName, sendException: false }, () =>
            this.currentStep(previousResult.value)
        )

        if (this.topHogOptions?.length && isOkResult(currentResult)) {
            const topHog = previousResultWithContext.context.topHog
            if (topHog) {
                const elapsedMs = performance.now() - startTime
                for (const metric of this.topHogOptions) {
                    const name = metric.name
                    const key = metric.key(previousResult.value)
                    switch (metric.type) {
                        case TopHogMetricType.Count:
                            topHog.increment(`${name}.count`, key)
                            break
                        case TopHogMetricType.Time:
                            topHog.increment(`${name}.time_ms`, key, elapsedMs)
                            break
                    }
                }
            }
        }

        return {
            result: currentResult,
            context: {
                ...previousResultWithContext.context,
                lastStep: this.stepName,
                sideEffects: [...previousResultWithContext.context.sideEffects, ...currentResult.sideEffects],
                warnings: [...previousResultWithContext.context.warnings, ...currentResult.warnings],
            },
        }
    }
}
