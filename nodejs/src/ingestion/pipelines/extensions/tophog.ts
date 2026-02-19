import type { TopHogPipeOptions } from '../../tophog/tophog'
import type { TopHogTracker } from '../pipeline.interface'
import type { ProcessingStep } from '../steps'
import { wrapStep } from './helpers'

export type TopHogWrapper = <T, U>(
    step: ProcessingStep<T, U>,
    descriptors: TopHogPipeOptions<T>
) => ProcessingStep<T, U>

export function createTopHogWrapper(tracker: TopHogTracker): TopHogWrapper {
    return <T, U>(step: ProcessingStep<T, U>, descriptors: TopHogPipeOptions<T>): ProcessingStep<T, U> => {
        if (!descriptors.length) {
            return step
        }
        return wrapStep(step, async (input, s) => {
            const ends = descriptors.map((d) => d.start(tracker, input))
            const result = await s(input)
            ends.forEach((end) => end())
            return result
        })
    }
}
