import { PostIngestionEvent } from '../../../types'
import { processComposeWebhookStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { runInstrumentedFunction } from '../../utils'
import { KafkaJSIngestionConsumer } from '../kafka-queue'

export async function handleComposeWebhookPlugins(
    event: PostIngestionEvent,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await runInstrumentedFunction({
        func: () => processComposeWebhookStep(queue.pluginsServer, event),
        statsKey: `kafka_queue.process_async_handlers_on_event`,
        timeoutMessage: 'After 30 seconds still running runAppsOnEventPipeline',
        timeoutContext: () => ({
            event: JSON.stringify(event),
        }),
        teamId: event.teamId,
    })
}
