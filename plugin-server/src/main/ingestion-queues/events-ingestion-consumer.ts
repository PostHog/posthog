import { Message } from 'node-rdkafka'

import { buildStringMatcher } from '../../config/config'
import { prefix as KAFKA_PREFIX, suffix as KAFKA_SUFFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchParallelIngestion, IngestionOverflowMode } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export type PipelineType = {
    topic: string
    consumer_group: string
}

export const PIPELINES: { [key: string]: PipelineType } = {
    ingestion_warnings: {
        topic: 'client_iwarnings_ingestion',
        consumer_group: 'client_iwarnings_ingestion',
    },
    heatmaps: {
        topic: 'heatmaps_ingestion',
        consumer_group: 'heatmaps_ingestion',
    },
    exceptions: {
        topic: 'exceptions_ingestion',
        consumer_group: 'exceptions_ingestion',
    },
}

export const startEventsIngestionPipelineConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    pipeline,
}: {
    hub: Hub
    pipeline: PipelineType
}) => {
    /*
        Consumes events from the topic and consumer passed in.
    */
    const kafka_topic = `${KAFKA_PREFIX}${pipeline.topic}${KAFKA_SUFFIX}`
    const kafka_consumer = `${KAFKA_PREFIX}${pipeline.consumer_group}`
    status.info(
        '🔁',
        `Starting events ingestion pipeline on topic ${kafka_topic} consumer ${kafka_consumer} with rdkafka`
    )

    const tokenBlockList = buildStringMatcher(hub.DROP_EVENTS_BY_TOKEN, false)
    // No overflow and split all events evenly, i.e. there's no ordering guarantees here.
    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(
            tokenBlockList,
            messages,
            queue,
            IngestionOverflowMode.ConsumeSplitEventlyWithoutIngestionWarning
        )
    }

    const queue = new IngestionConsumer(hub, kafka_topic, kafka_consumer, batchHandler)

    const { isHealthy } = await queue.start()

    return { queue, isHealthy }
}
