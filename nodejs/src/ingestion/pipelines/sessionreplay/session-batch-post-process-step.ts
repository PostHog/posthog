import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { SessionReplayPipelineOutput } from './session-replay-pipeline'

/**
 * Narrows the recorded element down to the pipeline's declared output ({@link SessionReplayPipelineOutput}).
 * The record step passes its rich input straight through; this projection makes the sub-pipeline's
 * output type exact, which the batching pipeline requires.
 */
export function createProjectReplayOutputStep<T extends SessionReplayPipelineOutput>(): ProcessingStep<
    T,
    SessionReplayPipelineOutput
> {
    return (input) => Promise.resolve(ok({ team: input.team, parsedMessage: input.parsedMessage }))
}
