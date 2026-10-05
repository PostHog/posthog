import { personDeletionPublishQueueCounter } from '~/common/persons/metrics'
import { PersonRepository } from '~/common/persons/repositories/person-repository'
import { generateKafkaPersonDeletionMessage } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'

import { PersonOutputs } from './person-context'

export interface PersonDeletionRepublisherConfig {
    /** How often the queue is read. */
    intervalMs: number
    /** How long a deletion record waits before it counts as lost, in seconds. */
    graceSeconds: number
    /** Records taken per pass. */
    batchSize: number
}

/**
 * Republishes the death documents of person deletions that committed in Postgres but
 * never reached ClickHouse, because the pod died between the merge's commit and its
 * produce. The merge records every deletion it is about to produce and clears the
 * record on the ack, so anything still in the queue after the grace period is a
 * deletion ClickHouse never heard about: the person survives there as a profile with
 * no events until the death document is produced again.
 */
export class PersonDeletionRepublisher {
    private timer?: NodeJS.Timeout
    private running = false

    constructor(
        private repository: PersonRepository,
        private outputs: PersonOutputs,
        private config: PersonDeletionRepublisherConfig
    ) {}

    start(): void {
        this.timer ??= setInterval(() => {
            void this.runOnce()
        }, this.config.intervalMs)
    }

    stop(): void {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
    }

    /**
     * One pass over the queue. Passes never overlap: a slow pass would otherwise claim
     * the records the previous one holds as soon as their attempt stamp ages out.
     */
    async runOnce(): Promise<number> {
        if (this.running) {
            return 0
        }
        this.running = true
        try {
            const pending = await this.repository.claimPersonDeletionPublishes(
                this.config.graceSeconds,
                this.config.batchSize
            )
            for (const deletion of pending) {
                const message = generateKafkaPersonDeletionMessage(
                    deletion.teamId,
                    deletion.personUuid,
                    deletion.personVersion
                )
                await this.outputs.produce(message.output, {
                    value: message.value,
                    key: null,
                    teamId: deletion.teamId,
                })
                // Cleared one at a time: a produce that fails halfway keeps the records
                // of the deletions still missing from ClickHouse.
                await this.repository.clearPersonDeletionPublishes(deletion.teamId, [deletion.personUuid])
                personDeletionPublishQueueCounter.labels({ action: 'republished' }).inc()
            }
            return pending.length
        } catch (error) {
            logger.warn('⚠️', 'Person deletion republish pass failed', { error: String(error) })
            return 0
        } finally {
            this.running = false
        }
    }
}
