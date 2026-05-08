import { MessageKey } from '../../kafka/producer'
import { IngestionOutput } from './ingestion-output'
import { SingleIngestionOutput } from './single-ingestion-output'
import { DualWriteMode, IngestionOutputMessage } from './types'

/**
 * Dual-write output — routes messages between primary and secondary based on mode.
 *
 * Percentage-based modes:
 * - `copy` — all messages go to primary; a percentage (by key hash) is also sent to secondary.
 * - `move` — a percentage (by key hash) goes to secondary only; the rest go to primary only.
 *
 * Team-denylist modes (use `teamIdDenylist`):
 * - `copy_team_denylist` — teams in denylist go to primary only; all others go to primary + secondary.
 * - `move_team_denylist` — teams in denylist go to primary only; all others go to secondary only.
 *
 * The builder never creates this class with `mode: 'off'` — it falls back to a plain SingleIngestionOutput.
 */
export class DualWriteIngestionOutput implements IngestionOutput {
    constructor(
        private readonly primary: SingleIngestionOutput,
        private readonly secondary: SingleIngestionOutput,
        private readonly mode: Exclude<DualWriteMode, 'off'>,
        private readonly percentage: number,
        private readonly teamIdDenylist: ReadonlySet<number> = new Set()
    ) {}

    async produce(message: IngestionOutputMessage & { key: MessageKey }): Promise<void> {
        const toSecondary = this.shouldRouteMessageToSecondary(message)

        if (this.isCopyMode()) {
            if (toSecondary) {
                await Promise.all([this.primary.produce(message), this.secondary.produce(message)])
            } else {
                await this.primary.produce(message)
            }
        } else {
            // move / move_team_denylist
            if (toSecondary) {
                await this.secondary.produce(message)
            } else {
                await this.primary.produce(message)
            }
        }
    }

    async queueMessages(messages: IngestionOutputMessage[]): Promise<void> {
        if (this.isCopyMode()) {
            const secondaryMessages = messages.filter((m) => this.shouldRouteMessageToSecondary(m))
            if (secondaryMessages.length > 0) {
                await Promise.all([
                    this.primary.queueMessages(messages),
                    this.secondary.queueMessages(secondaryMessages),
                ])
            } else {
                await this.primary.queueMessages(messages)
            }
        } else {
            // move / move_team_denylist — split messages between primary and secondary
            const primaryMessages: IngestionOutputMessage[] = []
            const secondaryMessages: IngestionOutputMessage[] = []
            for (const m of messages) {
                if (this.shouldRouteMessageToSecondary(m)) {
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

    private isCopyMode(): boolean {
        return this.mode === 'copy' || this.mode === 'copy_team_denylist'
    }

    private shouldRouteMessageToSecondary(message: IngestionOutputMessage): boolean {
        if (this.mode === 'copy_team_denylist' || this.mode === 'move_team_denylist') {
            return shouldRouteToSecondaryByTeam(message.teamId, this.teamIdDenylist)
        }
        return shouldRouteToSecondary(message.key ?? null, this.percentage)
    }
}

/**
 * Team-denylist routing decision.
 *
 * Returns `true` (route to secondary) when the team is NOT in the denylist and a teamId is present.
 * Returns `false` (stay on primary) when teamId is missing or the team is in the denylist.
 */
export function shouldRouteToSecondaryByTeam(teamId: number | undefined, denylist: ReadonlySet<number>): boolean {
    if (teamId === undefined) {
        return false
    }
    return !denylist.has(teamId)
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
