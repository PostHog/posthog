import { instrumentFn } from '~/common/tracing/tracing-utils'

import { PostIngestionEvent } from '../../../types'
import { processComposeWebhookStep } from '../../../worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { KafkaJSIngestionConsumer } from '../kafka-queue'

export async function handleComposeWebhookPlugins(
    event: PostIngestionEvent,
    queue: KafkaJSIngestionConsumer
): Promise<void> {
    await instrumentFn(
        {
            key: `kafka_queue.process_async_handlers_on_event`,
            getLoggingContext: () => ({
                event: JSON.stringify(event),
            }),
        },
        () => processComposeWebhookStep(queue.pluginsServer, event)
    )
}
