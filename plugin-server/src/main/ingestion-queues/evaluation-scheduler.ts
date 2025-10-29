/**
 * Evaluation Scheduler
 *
 * Consumes AI events (e.g., $ai_generation) from the main events stream,
 * matches them against evaluation filters, and triggers evaluation workflows
 * via Temporal when conditions are met.
 */
import * as crypto from 'crypto'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { execHog } from '../../cdp/utils/hog-exec'
import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { EvaluationManagerService } from '../../llm-analytics/services/evaluation-manager.service'
import { TemporalService } from '../../llm-analytics/services/temporal.service'
import { Evaluation, EvaluationConditionSet } from '../../llm-analytics/types'
import { Hub, PluginServerService, RawKafkaEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'

const evaluationSchedulerEventsProcessed = new Counter({
    name: 'evaluation_scheduler_events_processed',
    help: 'Number of AI events processed by evaluation scheduler',
    labelNames: ['status'],
})

const evaluationMatchesCounter = new Counter({
    name: 'evaluation_matches',
    help: 'Number of evaluation matches by outcome',
    labelNames: ['outcome'], // matched, filtered, sampling_excluded, error
})

const evaluationSchedulerMessagesReceived = new Counter({
    name: 'evaluation_scheduler_messages_received',
    help: 'Number of Kafka messages received before filtering',
})

const evaluationSchedulerEventsFiltered = new Counter({
    name: 'evaluation_scheduler_events_filtered',
    help: 'Number of events after productTrack header filter',
    labelNames: ['passed'],
})

// Pure functions for testability

export function filterAndParseMessages(messages: Message[]): RawKafkaEvent[] {
    return messages
        .filter((message) => {
            const headers = message.headers as { productTrack?: Buffer }[] | undefined
            return headers?.find((h) => h.productTrack)?.productTrack?.toString('utf8') === 'llma'
        })
        .map((message) => {
            try {
                return parseJSON(message.value!.toString()) as RawKafkaEvent
            } catch (e) {
                logger.error('Error parsing event', { error: e })
                return null
            }
        })
        .filter((event): event is RawKafkaEvent => event !== null)
}

export function groupEventsByTeam(events: RawKafkaEvent[]): Map<number, RawKafkaEvent[]> {
    const grouped = new Map<number, RawKafkaEvent[]>()
    for (const event of events) {
        const teamEvents = grouped.get(event.team_id) || []
        teamEvents.push(event)
        grouped.set(event.team_id, teamEvents)
    }
    return grouped
}

export function checkRolloutPercentage(distinctId: string, rolloutPercentage: number): boolean {
    if (rolloutPercentage >= 100) {
        return true
    }

    // Use MD5 hash for deterministic sampling
    const hash = crypto.createHash('md5').update(distinctId).digest('hex')
    const hashValue = parseInt(hash.substring(0, 8), 16)
    const percentage = (hashValue % 10000) / 100

    return percentage < rolloutPercentage
}

export async function checkConditionMatch(event: RawKafkaEvent, condition: EvaluationConditionSet): Promise<boolean> {
    if (!condition.bytecode) {
        if (condition.bytecode_error) {
            logger.warn('Condition has bytecode error, skipping', {
                conditionId: condition.id,
                error: condition.bytecode_error,
            })
        }
        return false
    }

    // Build globals for HogVM execution
    const filterGlobals = {
        event: event.event,
        elements_chain: event.elements_chain || '',
        distinct_id: event.distinct_id,
        person: {
            properties: {},
        },
        properties: parseJSON(event.properties || '{}'),
    }

    try {
        const execResult = await execHog(condition.bytecode, { globals: filterGlobals })

        if (execResult.error || execResult.execResult?.error) {
            logger.error('Error executing bytecode', {
                conditionId: condition.id,
                error: execResult.error ?? execResult.execResult?.error,
            })
            return false
        }

        return typeof execResult.execResult?.result === 'boolean' && execResult.execResult.result
    } catch (error: unknown) {
        logger.error('Exception executing bytecode', {
            conditionId: condition.id,
            error: error instanceof Error ? error.message : String(error),
        })
        return false
    }
}

export type EvaluationMatchResult =
    | { matched: true; conditionId: string }
    | { matched: false; reason: 'no_conditions' | 'disabled' | 'filtered' | 'sampling_excluded' }

export class EvaluationMatcher {
    async shouldTriggerEvaluation(event: RawKafkaEvent, evaluation: Evaluation): Promise<EvaluationMatchResult> {
        if (!evaluation.enabled) {
            return { matched: false, reason: 'disabled' }
        }

        const conditions = evaluation.conditions as EvaluationConditionSet[]
        if (conditions.length === 0) {
            return { matched: false, reason: 'no_conditions' }
        }

        for (const condition of conditions) {
            const conditionMatched = await checkConditionMatch(event, condition)

            if (!conditionMatched) {
                continue
            }

            const inSample = checkRolloutPercentage(event.distinct_id, condition.rollout_percentage)

            if (!inSample) {
                continue
            }

            return { matched: true, conditionId: condition.id }
        }

        return { matched: false, reason: 'filtered' }
    }
}

export const startEvaluationScheduler = async (hub: Hub): Promise<PluginServerService> => {
    logger.info('🤖', 'Starting evaluation scheduler')

    const temporalService = new TemporalService(hub)
    const evaluationManager = new EvaluationManagerService(hub)

    const kafkaConsumer = new KafkaConsumer({
        groupId: `${KAFKA_PREFIX}evaluation-scheduler`,
        topic: KAFKA_EVENTS_JSON,
    })

    await kafkaConsumer.connect((messages) =>
        eachBatchEvaluationScheduler(messages, evaluationManager, temporalService)
    )

    const onShutdown = async () => {
        await temporalService.disconnect()
        await kafkaConsumer.disconnect()
    }

    return {
        id: 'evaluation-scheduler',
        healthcheck: () => kafkaConsumer.isHealthy(),
        onShutdown,
    }
}

async function eachBatchEvaluationScheduler(
    messages: Message[],
    evaluationManager: EvaluationManagerService,
    temporalService: TemporalService
): Promise<void> {
    logger.debug('Processing batch', { messageCount: messages.length })

    evaluationSchedulerMessagesReceived.inc(messages.length)

    const aiGenerationEvents = filterAndParseMessages(messages)

    evaluationSchedulerEventsFiltered.labels({ passed: 'false' }).inc(messages.length - aiGenerationEvents.length)
    evaluationSchedulerEventsFiltered.labels({ passed: 'true' }).inc(aiGenerationEvents.length)

    logger.info('Filtered batch', {
        totalMessages: messages.length,
        aiEventsFound: aiGenerationEvents.length,
        filteredOut: messages.length - aiGenerationEvents.length,
    })

    if (aiGenerationEvents.length === 0) {
        return
    }

    logger.debug('Found $ai_generation events', { count: aiGenerationEvents.length })

    const eventsByTeam = groupEventsByTeam(aiGenerationEvents)
    const teamIds = Array.from(eventsByTeam.keys())

    const evaluationsByTeam = await evaluationManager.getEvaluationsForTeams(teamIds)
    const matcher = new EvaluationMatcher()
    const tasks: Promise<void>[] = []

    for (const [teamId, events] of eventsByTeam.entries()) {
        const evaluationDefinitions = evaluationsByTeam[teamId] || []

        if (evaluationDefinitions.length === 0) {
            continue
        }

        for (const event of events) {
            for (const evaluationDefinition of evaluationDefinitions) {
                const task = processEventEvaluationMatch(event, evaluationDefinition, matcher, temporalService).catch(
                    (error: unknown) => {
                        logger.error('Error processing evaluation', {
                            evaluationId: evaluationDefinition.id,
                            eventUuid: event.uuid,
                            error: error instanceof Error ? error.message : String(error),
                        })
                        evaluationMatchesCounter.labels({ outcome: 'error' }).inc()
                    }
                )

                tasks.push(task)
            }
        }
    }

    await Promise.allSettled(tasks)

    logger.info('Batch processing complete', {
        teamsProcessed: eventsByTeam.size,
        totalEvaluationChecks: tasks.length,
    })
}

async function processEventEvaluationMatch(
    event: RawKafkaEvent,
    evaluationDefinition: Evaluation,
    matcher: EvaluationMatcher,
    temporalService: TemporalService
): Promise<void> {
    evaluationSchedulerEventsProcessed.labels({ status: 'received' }).inc()

    const result = await matcher.shouldTriggerEvaluation(event, evaluationDefinition)

    if (!result.matched) {
        evaluationMatchesCounter.labels({ outcome: result.reason }).inc()
        return
    }

    logger.debug('Evaluation matched, enqueueing evaluation run', {
        evaluationId: evaluationDefinition.id,
        eventUuid: event.uuid,
        conditionId: result.conditionId,
    })

    evaluationMatchesCounter.labels({ outcome: 'matched' }).inc()

    await temporalService.startEvaluationRunWorkflow(evaluationDefinition.id, event.uuid)
    evaluationSchedulerEventsProcessed.labels({ status: 'success' }).inc()
}
