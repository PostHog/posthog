import { Message } from 'node-rdkafka'

import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpConsumerBase } from './cdp-base.consumer'

export interface CohortMembershipChange {
    personId: string
    cohortId: number
    teamId: number
}

export class CdpCohortMembershipConsumer extends CdpConsumerBase {
    protected name = 'CdpCohortMembershipConsumer'
    private kafkaConsumer: KafkaConsumer

    constructor(hub: Hub) {
        super(hub)
        // TODO: Update this to the actual topic name once it's defined
        const topic = 'COHORT_MEMBERSHIP_CHANGED'
        const groupId = 'cdp-cohort-membership-consumer'
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    private async handleCohortMembershipChange(change: CohortMembershipChange): Promise<void> {
        // For now, just log the data as requested
        logger.info('📊 Cohort membership change received', {
            personId: change.personId,
            cohortId: change.cohortId,
            teamId: change.teamId,
        })
        
        // TODO: Add actual processing logic here
    }

    private async handleBatch(messages: Message[]): Promise<void> {
        for (const message of messages) {
            try {
                const messageValue = message.value?.toString()
                if (!messageValue) {
                    logger.error('Empty message received')
                    continue
                }

                const cohortMembershipChange = parseJSON(messageValue) as CohortMembershipChange
                
                if (!cohortMembershipChange.personId || !cohortMembershipChange.cohortId || !cohortMembershipChange.teamId) {
                    logger.error('Invalid cohort membership change message', {
                        message: messageValue,
                    })
                    continue
                }

                await this.handleCohortMembershipChange(cohortMembershipChange)
            } catch (error) {
                logger.error('Error processing cohort membership change message', {
                    error,
                    message: message.value?.toString(),
                })
            }
        }
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