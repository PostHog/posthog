import { Message } from 'node-rdkafka'

/** Consumer batch item: `message.value` is Kafka bytes (Avro container); decode via `decodeLogRecords` → `LogRecord[]`. */
export type LogsIngestionMessage = {
    token: string
    teamId: number
    message: Message
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
}
