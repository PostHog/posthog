import { Message } from 'node-rdkafka'

export type MetricsIngestionMessage = {
    token: string
    teamId: number
    message: Message
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
}
