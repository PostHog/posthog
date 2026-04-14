import { MessageKey } from '../../kafka/producer'
import { IngestionOutput } from './ingestion-output'
import { IngestionOutputMessage } from './types'

/**
 * Routes messages to different outputs based on team ID.
 *
 * Messages whose `teamId` is in the configured set are sent to the
 * `teamOutput`; everything else goes to `defaultOutput`. For `queueMessages`,
 * the batch is split by team membership and each sub-batch is sent to the
 * appropriate output in parallel.
 *
 * Health checks and topic checks cover both outputs.
 */
export class TeamRoutedIngestionOutput implements IngestionOutput {
    constructor(
        private readonly defaultOutput: IngestionOutput,
        private readonly teamOutput: IngestionOutput,
        private readonly teamIds: ReadonlySet<number>
    ) {}

    async produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        if (message.teamId !== undefined && this.teamIds.has(message.teamId)) {
            return this.teamOutput.produce(message)
        }
        return this.defaultOutput.produce(message)
    }

    async queueMessages(messages: IngestionOutputMessage[]): Promise<void> {
        const defaultMessages: IngestionOutputMessage[] = []
        const teamMessages: IngestionOutputMessage[] = []

        for (const msg of messages) {
            if (msg.teamId !== undefined && this.teamIds.has(msg.teamId)) {
                teamMessages.push(msg)
            } else {
                defaultMessages.push(msg)
            }
        }

        const promises: Promise<void>[] = []
        if (defaultMessages.length > 0) {
            promises.push(this.defaultOutput.queueMessages(defaultMessages))
        }
        if (teamMessages.length > 0) {
            promises.push(this.teamOutput.queueMessages(teamMessages))
        }
        await Promise.all(promises)
    }

    async checkHealth(timeoutMs: number): Promise<void> {
        await Promise.all([this.defaultOutput.checkHealth(timeoutMs), this.teamOutput.checkHealth(timeoutMs)])
    }

    async checkTopicExists(timeoutMs: number): Promise<void> {
        await Promise.all([this.defaultOutput.checkTopicExists(timeoutMs), this.teamOutput.checkTopicExists(timeoutMs)])
    }
}
