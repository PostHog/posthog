import { PreIngestionEvent } from '../../../types'
import { shouldSendEventToBuffer } from '../ingest-event'
import { EventPipelineRunner, StepResult } from './runner'

export async function determineShouldBufferStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent
): Promise<StepResult> {
    const person = await runner.hub.db.fetchPerson(event.teamId, event.distinctId)

    // even if the buffer is disabled we want to get metrics on how many events would have gone to it
    const sendEventToBuffer = shouldSendEventToBuffer(runner.hub, event, person, event.teamId)

    if (sendEventToBuffer) {
        await runner.hub.eventsProcessor.produceEventToBuffer(event)
        return null
    } else {
        return runner.nextStep('createEventStep', event, person)
    }
}
