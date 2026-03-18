import { Message } from 'node-rdkafka'

export type LogsIngestionMessage = {
    token: string
    teamId: number
    message: Message
    bytesUncompressed: number
    bytesCompressed: number
    recordCount: number
}
