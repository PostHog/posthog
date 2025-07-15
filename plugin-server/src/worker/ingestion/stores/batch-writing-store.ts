import { TopicMessage } from '../../../kafka/producer'

export interface BatchWritingStore {
    /*
     * Flushes all batch data that needs to be written
     * Returns Kafka messages that need to be sent
     */
    flush(): Promise<TopicMessage[]>
}
