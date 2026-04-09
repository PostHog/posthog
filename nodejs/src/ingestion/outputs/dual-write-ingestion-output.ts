import { MessageKey } from '../../kafka/producer'
import { IngestionOutput } from './ingestion-output'
import { SingleIngestionOutput } from './single-ingestion-output'
import { DualWriteMode, IngestionOutputMessage } from './types'

/**
 * Dual-write output — routes messages between primary and secondary based on mode and percentage.
 *
 * - `copy` mode: all messages go to primary; a percentage (by key hash) is also sent to secondary.
 * - `move` mode: a percentage (by key hash) goes to secondary only; the rest go to primary only.
 *
 * The builder never creates this class with `mode: 'off'` — it falls back to a plain SingleIngestionOutput.
 */
export class DualWriteIngestionOutput implements IngestionOutput {
    constructor(
        private readonly primary: SingleIngestionOutput,
        private readonly secondary: SingleIngestionOutput,
        private readonly mode: Exclude<DualWriteMode, 'off'>,
        private readonly percentage: number
    ) {}

    async produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        const toSecondary = shouldRouteToSecondary(message.key, this.percentage)

        if (this.mode === 'copy') {
            if (toSecondary) {
                await Promise.all([this.primary.produce(message), this.secondary.produce(message)])
            } else {
                await this.primary.produce(message)
            }
        } else {
            // move
            if (toSecondary) {
                await this.secondary.produce(message)
            } else {
                await this.primary.produce(message)
            }
        }
    }

    async queueMessages(messages: IngestionOutputMessage[]): Promise<void> {
        if (this.mode === 'copy') {
            const secondaryMessages = messages.filter((m) => shouldRouteToSecondary(m.key ?? null, this.percentage))
            if (secondaryMessages.length > 0) {
                await Promise.all([
                    this.primary.queueMessages(messages),
                    this.secondary.queueMessages(secondaryMessages),
                ])
            } else {
                await this.primary.queueMessages(messages)
            }
        } else {
            // move — split messages between primary and secondary
            const primaryMessages: IngestionOutputMessage[] = []
            const secondaryMessages: IngestionOutputMessage[] = []
            for (const m of messages) {
                if (shouldRouteToSecondary(m.key ?? null, this.percentage)) {
                    secondaryMessages.push(m)
                } else {
                    primaryMessages.push(m)
                }
            }
            const promises: Promise<void>[] = []
            if (primaryMessages.length > 0) {
                promises.push(this.primary.queueMessages(primaryMessages))
            }
            if (secondaryMessages.length > 0) {
                promises.push(this.secondary.queueMessages(secondaryMessages))
            }
            if (promises.length > 0) {
                await Promise.all(promises)
            }
        }
    }

    async checkHealth(timeoutMs: number): Promise<void> {
        await Promise.all([this.primary.checkHealth(timeoutMs), this.secondary.checkHealth(timeoutMs)])
    }

    async checkTopicExists(timeoutMs: number): Promise<void> {
        await Promise.all([this.primary.checkTopicExists(timeoutMs), this.secondary.checkTopicExists(timeoutMs)])
    }
}

/**
 * Deterministic routing decision based on a hash of the message key.
 *
 * Uses FNV-1a 32-bit for a fast, well-distributed hash. The same key always
 * produces the same decision, so related messages (e.g. same distinct_id) stay
 * on the same target.
 *
 * Messages with a null/undefined key are routed randomly based on the percentage,
 * since the absence of a key means ordering doesn't matter for that message.
 */
export function shouldRouteToSecondary(key: MessageKey | null | undefined, percentage: number): boolean {
    if (percentage <= 0) {
        return false
    }
    if (percentage >= 100) {
        return true
    }
    if (!key) {
        return Math.random() * 100 < percentage
    }
    return keyHashBucket(key) < percentage
}

/** FNV-1a 32-bit hash of a message key, reduced to a 0–99 bucket. */
export function keyHashBucket(key: Buffer | string): number {
    const buf = Buffer.isBuffer(key) ? key : Buffer.from(key)
    let hash = 0x811c9dc5
    for (let i = 0; i < buf.length; i++) {
        hash ^= buf[i]
        hash = Math.imul(hash, 0x01000193) >>> 0
    }
    return hash % 100
}
