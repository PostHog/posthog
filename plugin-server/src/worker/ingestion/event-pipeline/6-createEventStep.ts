import { PreIngestionEvent } from '../../../types'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner, StepResult } from './runner'

export async function createEventStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    personContainer: LazyPersonContainer
): Promise<StepResult> {
    await runner.hub.eventsProcessor.createEvent(event, personContainer)
    // NOTE: we always stop here. Previously we had an optimization to run the
    // async functions within this pipeline. Instead we unify how the pipeline
    // runs no matter how you have PLUGIN_SERVER_MODE set.
    return null
}
