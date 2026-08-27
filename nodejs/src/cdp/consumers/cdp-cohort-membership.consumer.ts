import { Message } from 'node-rdkafka'
import { z } from 'zod'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult } from '../../types'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'

// The processor stamps `origin` and `run_id` on backfill changes and omits both on live
// transitions. `z.object` drops unknown keys, so any field the consumer must read has to be
// declared here.
//
// `origin` is a tolerant string, not a strict enum, because the consumer upserts the same way for
// every origin and never branches on the value. A strict enum would reject an origin it does not
// know, and rejection throws the whole batch: `_parseAndValidateBatch` re-throws to the consumer
// loop, the service shuts down, and because offsets store only after a successful batch the
// message redelivers on restart into a crash loop. The Rust `ChangeOrigin` enum is additive (new
// origins land with their producers), so a processor deploy can emit an origin this consumer has
// not seen. Known values today: `seed` (initial backfill snapshot), `reconcile` (backfill drift
// replay), absent (live transition).
//
// `run_id` identifies the backfill run and is carried for the mark-and-sweep deletion work, which
// uses it to delete rows a completed run did not re-assert.
const CohortMembershipChangeSchema = z.object({
    person_id: z.guid(),
    cohort_id: z.number(),
    team_id: z.number(),
    status: z.enum(['entered', 'left']),
    last_updated: z.string().optional(),
    origin: z.string().optional(),
    run_id: z.guid().optional(),
})

export type CohortMembershipChange = z.infer<typeof CohortMembershipChangeSchema>

export class CdpCohortMembershipConsumer extends CdpConsumerBase {
    protected name = 'CdpCohortMembershipConsumer'
    private kafkaConsumer: KafkaConsumerInterface

    constructor(config: CdpConsumerBaseConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-cohort-membership-consumer',
            topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
        })
    }

    private async persistCohortMembershipChanges(changes: CohortMembershipChange[]): Promise<void> {
        if (changes.length === 0) {
            return
        }

        try {
            // Deduplicate by (team_id, cohort_id, person_id), keeping last in Kafka order
            const deduped = new Map<string, CohortMembershipChange>()
            for (const change of changes) {
                deduped.set(`${change.team_id}:${change.cohort_id}:${change.person_id}`, change)
            }

            // Build the VALUES clause for batch upsert
            const values: any[] = []
            const placeholders: string[] = []
            let paramIndex = 1

            for (const change of deduped.values()) {
                const inCohort = change.status === 'entered'
                placeholders.push(
                    `($${paramIndex}, $${paramIndex + 1}, $${paramIndex + 2}, $${paramIndex + 3}, CURRENT_TIMESTAMP)`
                )
                values.push(change.team_id, change.cohort_id, change.person_id, inCohort)
                paramIndex += 4
            }

            // Single batch UPSERT query - handles both entered and left events
            const query = `
                INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, last_updated)
                VALUES ${placeholders.join(', ')}
                ON CONFLICT (team_id, cohort_id, person_id)
                DO UPDATE SET
                    in_cohort = EXCLUDED.in_cohort,
                    last_updated = CURRENT_TIMESTAMP
            `

            await this.deps.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                query,
                values,
                'batchUpsertCohortMembership'
            )
        } catch (error) {
            logger.error('Failed to process batch cohort membership changes', {
                error,
                count: changes.length,
            })
            throw error
        }
    }

    private _parseAndValidateBatch(messages: Message[]): CohortMembershipChange[] {
        const cohortMembershipChanges: CohortMembershipChange[] = []

        // Process and validate all messages
        for (const message of messages) {
            try {
                const messageValue = message.value?.toString()
                if (!messageValue) {
                    throw new Error('Empty message received')
                }

                const parsedMessage = parseJSON(messageValue)

                // Validate using Zod schema
                const validationResult = CohortMembershipChangeSchema.safeParse(parsedMessage)

                if (!validationResult.success) {
                    logger.error('Invalid cohort membership change message', {
                        errors: validationResult.error.issues,
                        message: messageValue,
                    })
                    throw new Error(`Invalid cohort membership change message: ${validationResult.error.message}`)
                }

                const cohortMembershipChange = validationResult.data
                cohortMembershipChanges.push(cohortMembershipChange)
            } catch (error) {
                logger.error('Error processing cohort membership change message', {
                    error,
                    message: message.value?.toString(),
                })
                throw error
            }
        }

        return cohortMembershipChanges
    }

    public override async start(): Promise<void> {
        await super.start()

        logger.info('🚀', `${this.name} starting...`)

        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return instrumentFn('cdpCohortMembershipConsumer.handleEachBatch', async () => {
                const cohortMembershipChanges = this._parseAndValidateBatch(messages)
                await this.persistCohortMembershipChanges(cohortMembershipChanges)
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
