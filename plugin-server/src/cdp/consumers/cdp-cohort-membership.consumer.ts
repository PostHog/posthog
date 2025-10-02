import { Message } from 'node-rdkafka'
import { z } from 'zod'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpConsumerBase } from './cdp-base.consumer'

// Zod schema for validation
const CohortMembershipChangeSchema = z.object({
    personId: z.number(),
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
        const topic = KAFKA_COHORT_MEMBERSHIP_CHANGED
        const groupId = 'cdp-cohort-membership-consumer'
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    private async handleBatchJoinedCohort(changes: CohortMembershipChange[]): Promise<void> {
        if (changes.length === 0) {
            return
        }

        logger.info('Batch processing persons who joined cohorts', {
            count: changes.length,
            sample: changes.slice(0, 3).map((c) => ({
                personId: c.personId,
                cohortId: c.cohortId,
                teamId: c.teamId,
            })),
        })

        await Promise.resolve()

        // TODO: Batch insert/update entries in postgres database
        // This would typically involve:
        // - Prepare batch insert/update query
        // - Use ON CONFLICT to handle existing entries
        // - Execute single query for all changes
    }

    private async handleBatchLeftCohort(changes: CohortMembershipChange[]): Promise<void> {
        if (changes.length === 0) {
            return
        }

        logger.info('Batch processing persons who left cohorts', {
            count: changes.length,
            sample: changes.slice(0, 3).map((c) => ({
                personId: c.personId,
                cohortId: c.cohortId,
                teamId: c.teamId,
            })),
        })

        // TODO: Batch delete/update entries in postgres database
        // This would typically involve:
        // - Prepare batch delete query or update query (for soft deletes)
        // - Execute single query for all changes
        // - Handle any cascading updates if necessary
        await Promise.resolve()
    }

    private async handleBatch(messages: Message[]): Promise<void> {
        // Aggregate events by action type
        const enteredCohort: CohortMembershipChange[] = []
        const leftCohort: CohortMembershipChange[] = []

        // Process and validate all messages
        for (const message of messages) {
            try {
                const messageValue = message.value?.toString()
                if (!messageValue) {
                    logger.error('Empty message received')
                    continue
                }

                const parsedMessage = parseJSON(messageValue)

                // Validate using Zod schema
                const validationResult = CohortMembershipChangeSchema.safeParse(parsedMessage)

                if (!validationResult.success) {
                    logger.error('Invalid cohort membership change message', {
                        errors: validationResult.error.errors,
                        message: messageValue,
                    })
                    continue
                }

                const cohortMembershipChange = validationResult.data

                // Aggregate based on the cohort_membership_changed property
                switch (cohortMembershipChange.cohort_membership_changed) {
                    case 'entered':
                        enteredCohort.push(cohortMembershipChange)
                        break
                    case 'left':
                        leftCohort.push(cohortMembershipChange)
                        break
                }
            } catch (error) {
                logger.error('Error processing cohort membership change message', {
                    error,
                    message: message.value?.toString(),
                })
            }
        }

        // Process batches
        await Promise.all([this.handleBatchJoinedCohort(enteredCohort), this.handleBatchLeftCohort(leftCohort)])
    }

    public async start(): Promise<void> {
        await super.start()

        logger.info('🚀', `${this.name} starting...`)

        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            await this.runWithHeartbeat(() => this.handleBatch(messages))
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
