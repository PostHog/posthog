import { Message } from 'node-rdkafka'
import { z } from 'zod'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpConsumerBase } from './cdp-base.consumer'

// Zod schema for validation
const CohortMembershipChangeSchema = z.object({
    personId: z.string().uuid(),
    cohortId: z.number(),
    teamId: z.number(),
    cohort_membership_changed: z.enum(['entered', 'left']),
})

export type CohortMembershipChange = z.infer<typeof CohortMembershipChangeSchema>

export class CdpCohortMembershipConsumer extends CdpConsumerBase {
    protected name = 'CdpCohortMembershipConsumer'
    private kafkaConsumer: KafkaConsumer

    constructor(hub: Hub) {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({
            groupId: 'cdp-cohort-membership-consumer',
            topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
        })
    }

    private async handleBatchCohortMembership(changes: CohortMembershipChange[]): Promise<void> {
        if (changes.length === 0) {
            return
        }

        try {
            // Build the VALUES clause for batch upsert
            const values: any[] = []
            const placeholders: string[] = []
            let paramIndex = 1

            for (const change of changes) {
                const inCohort = change.cohort_membership_changed === 'entered'
                placeholders.push(
                    `($${paramIndex}, $${paramIndex + 1}, $${paramIndex + 2}, $${paramIndex + 3}, CURRENT_TIMESTAMP)`
                )
                values.push(change.teamId, change.cohortId, change.personId, inCohort)
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

            await this.hub.postgres.query(
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

    private async handleBatch(messages: Message[]): Promise<void> {
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
                        errors: validationResult.error.errors,
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

        await this.handleBatchCohortMembership(cohortMembershipChanges)
    }

    public async start(): Promise<void> {
        await super.start()

        logger.info('🚀', `${this.name} starting...`)

        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            await this.handleBatch(messages)
        })

        logger.info('✅', `${this.name} started successfully`)
    }

    public async stop(): Promise<void> {
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
