/**
 * Evaluation Scheduler
 *
 * Consumes AI events (e.g., $ai_generation) from the ai_events Kafka topic
 * (clickhouse_ai_events_json), matches them against evaluation filters, and
 * triggers evaluation workflows via Temporal when conditions are met.
 *
 * The ai_events topic carries the unstripped event payload (the events topic
 * has the heavy AI properties stripped), so the judge always sees the full
 * input/output it needs to grade.
 */
import * as crypto from 'crypto'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { AIObservabilityConfig } from '~/ai-observability/config'
import { EvaluationManagerService } from '~/ai-observability/services/evaluation-manager.service'
import { ProviderKeyManagerService } from '~/ai-observability/services/provider-key-manager.service'
import { TaggerManagerService } from '~/ai-observability/services/tagger-manager.service'
import {
    DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS,
    TemporalService,
    TemporalServiceConfig,
    isEvaluationWorkflowRuntime,
} from '~/ai-observability/services/temporal.service'
import { Evaluation, EvaluationConditionSet, Matchable, Tagger } from '~/ai-observability/types'
import { execHog } from '~/cdp/utils/hog-exec'
import { KAFKA_CLICKHOUSE_AI_EVENTS_JSON, prefix as KAFKA_PREFIX } from '~/common/config/kafka-topics'
import { createKafkaConsumer } from '~/common/kafka/consumer'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { PluginServerService, RawKafkaEvent } from '~/types'

export type EvaluationSchedulerConfig = TemporalServiceConfig &
    Pick<AIObservabilityConfig, 'LLMA_EVAL_SCHEDULER_PROVIDER_KEY_GATING'>

export interface EvaluationSchedulerDeps {
    postgres: PostgresRouter
    pubSub: PubSub
}

const evaluationSchedulerEventsProcessed = new Counter({
    name: 'evaluation_scheduler_events_processed',
    help: 'Number of AI events processed by evaluation scheduler',
    labelNames: ['status', 'type'], // type: 'evaluation' | 'tagger' — keep existing eval alerts working while exposing tagger traffic
})

const evaluationMatchesCounter = new Counter({
    name: 'evaluation_matches',
    help: 'Number of evaluation matches by outcome',
    labelNames: ['outcome', 'type'], // matched, filtered, sampling_excluded, error × evaluation/tagger
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

const evaluationSchedulerHeaderValues = new Counter({
    name: 'evaluation_scheduler_header_values',
    help: 'Count of different productTrack header values seen',
    labelNames: ['header_value'],
})

// Pure functions for testability

/**
 * Pull the value out of an awaited Promise.allSettled entry, falling back to an
 * empty object map and logging the rejection reason. Used to keep the scheduler
 * loop alive when one fetch fails without losing the other one's results.
 */
export function unwrapOrLog<T extends Record<string, unknown>>(
    result: PromiseSettledResult<T>,
    errorMessage: string
): T {
    if (result.status === 'fulfilled') {
        return result.value
    }
    logger.error(errorMessage, {
        error: result.reason instanceof Error ? result.reason.message : String(result.reason),
    })
    return {} as T
}

export function filterAndParseMessages(messages: Message[]): RawKafkaEvent[] {
    return messages
        .filter((message) => {
            const headers = message.headers as { productTrack?: Buffer }[] | undefined
            const productTrack = headers?.find((h) => h.productTrack)?.productTrack?.toString('utf8')

            evaluationSchedulerHeaderValues.labels({ header_value: productTrack || 'missing' }).inc()

            return productTrack === 'llma'
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
        .filter((event) => event.event === '$ai_generation')
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

/**
 * Pull the trace linkage out of an event's properties. Trace ids are user-controlled and can
 * be ingested as numbers (e.g. a buggy `trace_id: 0`), so values are string-coerced; empty or
 * missing ids resolve to null.
 */
export function extractTraceContext(event: RawKafkaEvent): { traceId: string | null; sessionId: string | null } {
    let properties: Record<string, unknown> = {}
    try {
        properties = parseJSON(event.properties || '{}')
    } catch {
        return { traceId: null, sessionId: null }
    }
    const coerce = (value: unknown): string | null =>
        value === null || value === undefined || value === '' ? null : String(value)
    return {
        traceId: coerce(properties['$ai_trace_id']),
        sessionId: coerce(properties['$session_id']),
    }
}

export function checkRolloutPercentage(eventId: string, rolloutPercentage: number): boolean {
    if (rolloutPercentage >= 100) {
        return true
    }

    // Use MD5 hash for deterministic sampling
    const hash = crypto.createHash('md5').update(eventId).digest('hex')
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
    let personProperties = {}
    let eventProperties = {}

    try {
        personProperties = parseJSON(event.person_properties || '{}')
    } catch (e) {
        logger.warn('Failed to parse person_properties', {
            conditionId: condition.id,
            eventUuid: event.uuid,
            error: e instanceof Error ? e.message : String(e),
        })
    }

    try {
        eventProperties = parseJSON(event.properties || '{}')
    } catch (e) {
        logger.warn('Failed to parse event properties', {
            conditionId: condition.id,
            eventUuid: event.uuid,
            error: e instanceof Error ? e.message : String(e),
        })
    }

    const filterGlobals = {
        event: event.event,
        elements_chain: event.elements_chain || '',
        distinct_id: event.distinct_id,
        person: {
            properties: personProperties,
        },
        properties: eventProperties,
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
    /**
     * `samplingKey` defaults to the event uuid (independent coin flip per generation). Trace-
     * target evals pass the trace id instead so the whole trace is atomically in or out of the
     * sample, no matter which of its generations is seen first.
     */
    async shouldTriggerEvaluation(
        event: RawKafkaEvent,
        evaluation: Matchable,
        samplingKey?: string
    ): Promise<EvaluationMatchResult> {
        if (!evaluation.enabled) {
            return { matched: false, reason: 'disabled' }
        }

        const conditions = evaluation.conditions
        if (conditions.length === 0) {
            return { matched: false, reason: 'no_conditions' }
        }

        for (const condition of conditions) {
            const conditionMatched = await checkConditionMatch(event, condition)

            if (!conditionMatched) {
                continue
            }

            const inSample = checkRolloutPercentage(samplingKey ?? event.uuid, condition.rollout_percentage)

            if (!inSample) {
                continue
            }

            return { matched: true, conditionId: condition.id }
        }

        return { matched: false, reason: 'filtered' }
    }
}

export const startEvaluationScheduler = async (
    config: EvaluationSchedulerConfig,
    deps: EvaluationSchedulerDeps
): Promise<PluginServerService> => {
    const groupId = `${KAFKA_PREFIX}evaluation-scheduler-ai-events`
    const kafkaTopic = KAFKA_CLICKHOUSE_AI_EVENTS_JSON

    logger.info('🤖', 'Starting evaluation scheduler', {
        groupId,
        kafkaTopic,
        providerKeyGating: config.LLMA_EVAL_SCHEDULER_PROVIDER_KEY_GATING,
    })

    const temporalService = new TemporalService(config)
    const evaluationManager = new EvaluationManagerService(deps.postgres, deps.pubSub)
    const taggerManager = new TaggerManagerService(deps.postgres, deps.pubSub)
    const providerKeyManager = config.LLMA_EVAL_SCHEDULER_PROVIDER_KEY_GATING
        ? new ProviderKeyManagerService(deps.postgres, deps.pubSub)
        : undefined

    const kafkaConsumer = createKafkaConsumer({
        groupId,
        topic: kafkaTopic,
    })

    await kafkaConsumer.connect((messages) =>
        eachBatchEvaluationScheduler(messages, evaluationManager, taggerManager, temporalService, {
            enabled: config.LLMA_EVAL_SCHEDULER_PROVIDER_KEY_GATING,
            providerKeyManager,
        })
    )

    const onShutdown = async (): Promise<void> => {
        await temporalService.disconnect()
        await kafkaConsumer.disconnect()
    }

    return {
        id: 'evaluation-scheduler',
        healthcheck: () => kafkaConsumer.isHealthy(),
        onShutdown,
    }
}

export interface ProviderKeyGateOptions {
    enabled: boolean
    providerKeyManager?: Pick<ProviderKeyManagerService, 'getProviderKey'>
}

type ProviderKeyGateDefinition = {
    id: string
    team_id: number
    provider_key_id?: string | null
    evaluation_type?: string
    tagger_type?: string
}

const NON_PROVIDER_KEY_RUNTIMES = new Set(['hog', 'sentiment'])

function definitionUsesProviderKey(definition: ProviderKeyGateDefinition): boolean {
    const runtime = definition.evaluation_type ?? definition.tagger_type
    return !runtime || !NON_PROVIDER_KEY_RUNTIMES.has(runtime)
}

export async function eachBatchEvaluationScheduler(
    messages: Message[],
    evaluationManager: EvaluationManagerService,
    taggerManager: TaggerManagerService,
    temporalService: TemporalService,
    providerKeyGate?: ProviderKeyGateOptions
): Promise<void> {
    logger.debug('Processing batch', { messageCount: messages.length })

    evaluationSchedulerMessagesReceived.inc(messages.length)

    const aiGenerationEvents = filterAndParseMessages(messages)

    evaluationSchedulerEventsFiltered.labels({ passed: 'false' }).inc(messages.length - aiGenerationEvents.length)
    evaluationSchedulerEventsFiltered.labels({ passed: 'true' }).inc(aiGenerationEvents.length)

    logger.debug('Filtered batch', {
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

    // Fetch evaluations and taggers independently — a transient DB failure on one
    // side must not take down dispatch for the other. If either side fails we log
    // and fall back to an empty map so the matched workflows just don't trigger
    // this batch, instead of failing the whole Kafka consumer loop.
    const [evaluationsResult, taggersResult] = await Promise.allSettled([
        evaluationManager.getEvaluationsForTeams(teamIds),
        taggerManager.getTaggersForTeams(teamIds),
    ])
    const evaluationsByTeam = unwrapOrLog(evaluationsResult, 'Failed to fetch evaluations for teams')
    const taggersByTeam = unwrapOrLog(taggersResult, 'Failed to fetch taggers for teams')
    const matcher = new EvaluationMatcher()
    const tasks: Promise<void>[] = []

    for (const [teamId, events] of eventsByTeam.entries()) {
        const evaluationDefinitions = evaluationsByTeam[teamId] || []
        const taggerDefinitions = taggersByTeam[teamId] || []

        if (evaluationDefinitions.length === 0 && taggerDefinitions.length === 0) {
            continue
        }

        for (const event of events) {
            for (const evaluationDefinition of evaluationDefinitions) {
                const task = processEventEvaluationMatch(
                    event,
                    evaluationDefinition,
                    matcher,
                    temporalService,
                    providerKeyGate
                ).catch((error: unknown) => {
                    logger.error('Error processing evaluation', {
                        evaluationId: evaluationDefinition.id,
                        eventUuid: event.uuid,
                        error: error instanceof Error ? error.message : String(error),
                    })
                    evaluationMatchesCounter.labels({ outcome: 'error', type: 'evaluation' }).inc()
                })

                tasks.push(task)
            }

            for (const taggerDefinition of taggerDefinitions) {
                const task = processEventTaggerMatch(
                    event,
                    taggerDefinition,
                    matcher,
                    temporalService,
                    providerKeyGate
                ).catch((error: unknown) => {
                    logger.error('Error processing tagger', {
                        taggerId: taggerDefinition.id,
                        eventUuid: event.uuid,
                        error: error instanceof Error ? error.message : String(error),
                    })
                    evaluationMatchesCounter.labels({ outcome: 'error', type: 'tagger' }).inc()
                })

                tasks.push(task)
            }
        }
    }

    await Promise.allSettled(tasks)

    logger.debug('Batch processing complete', {
        teamsProcessed: eventsByTeam.size,
        totalChecks: tasks.length,
    })
}

async function processEventEvaluationMatch(
    event: RawKafkaEvent,
    evaluationDefinition: Evaluation,
    matcher: EvaluationMatcher,
    temporalService: TemporalService,
    providerKeyGate?: ProviderKeyGateOptions
): Promise<void> {
    evaluationSchedulerEventsProcessed.labels({ status: 'received', type: 'evaluation' }).inc()

    const isTraceTarget = evaluationDefinition.target === 'trace'
    let traceContext: ReturnType<typeof extractTraceContext> | null = null
    if (isTraceTarget) {
        traceContext = extractTraceContext(event)
        if (!traceContext.traceId) {
            evaluationMatchesCounter.labels({ outcome: 'no_trace_id', type: 'evaluation' }).inc()
            return
        }
    }

    const result = await matcher.shouldTriggerEvaluation(
        event,
        evaluationDefinition,
        traceContext?.traceId ?? undefined
    )

    if (!result.matched) {
        evaluationMatchesCounter.labels({ outcome: result.reason, type: 'evaluation' }).inc()
        return
    }

    const providerKeySkipOutcome = await getProviderKeySkipOutcome(evaluationDefinition, providerKeyGate)
    if (providerKeySkipOutcome) {
        evaluationMatchesCounter.labels({ outcome: providerKeySkipOutcome, type: 'evaluation' }).inc()
        return
    }

    logger.debug('Evaluation matched, enqueueing evaluation run', {
        evaluationId: evaluationDefinition.id,
        eventUuid: event.uuid,
        traceId: traceContext?.traceId,
        conditionId: result.conditionId,
    })

    evaluationMatchesCounter.labels({ outcome: 'matched', type: 'evaluation' }).inc()

    if (isTraceTarget && traceContext?.traceId) {
        // No isEvaluationWorkflowRuntime guard here: the trace workflow validates evaluation_type
        // server-side and rejects unsupported types as a non-retryable ApplicationError.
        const windowSeconds =
            evaluationDefinition.target_config?.window_seconds ?? DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS
        await temporalService.startTraceEvaluationRunWorkflow(
            evaluationDefinition.id,
            event,
            traceContext.traceId,
            traceContext.sessionId,
            windowSeconds
        )
    } else {
        const evaluationRuntime = evaluationDefinition.evaluation_type
        if (!isEvaluationWorkflowRuntime(evaluationRuntime)) {
            throw new Error(`Unsupported evaluation runtime: ${evaluationRuntime}`)
        }

        await temporalService.startEvaluationRunWorkflow(evaluationDefinition.id, event, evaluationRuntime)
    }
    evaluationSchedulerEventsProcessed.labels({ status: 'success', type: 'evaluation' }).inc()
}

async function processEventTaggerMatch(
    event: RawKafkaEvent,
    taggerDefinition: Tagger,
    matcher: EvaluationMatcher,
    temporalService: TemporalService,
    providerKeyGate?: ProviderKeyGateOptions
): Promise<void> {
    evaluationSchedulerEventsProcessed.labels({ status: 'received', type: 'tagger' }).inc()

    // Taggers use the same conditions structure as evaluations
    const result = await matcher.shouldTriggerEvaluation(event, taggerDefinition)

    if (!result.matched) {
        evaluationMatchesCounter.labels({ outcome: result.reason, type: 'tagger' }).inc()
        return
    }

    const providerKeySkipOutcome = await getProviderKeySkipOutcome(taggerDefinition, providerKeyGate)
    if (providerKeySkipOutcome) {
        evaluationMatchesCounter.labels({ outcome: providerKeySkipOutcome, type: 'tagger' }).inc()
        return
    }

    logger.debug('Tagger matched, enqueueing tagger run', {
        taggerId: taggerDefinition.id,
        eventUuid: event.uuid,
        conditionId: result.conditionId,
    })

    evaluationMatchesCounter.labels({ outcome: 'matched', type: 'tagger' }).inc()

    await temporalService.startTaggerRunWorkflow(taggerDefinition.id, event)
    evaluationSchedulerEventsProcessed.labels({ status: 'success', type: 'tagger' }).inc()
}

async function getProviderKeySkipOutcome(
    definition: ProviderKeyGateDefinition,
    providerKeyGate?: ProviderKeyGateOptions
): Promise<'provider_key_not_ok' | 'provider_key_not_found' | 'provider_key_team_mismatch' | null> {
    if (!providerKeyGate?.enabled || !providerKeyGate.providerKeyManager) {
        return null
    }

    if (!definitionUsesProviderKey(definition)) {
        return null
    }

    const providerKeyId = definition.provider_key_id
    if (!providerKeyId) {
        return null
    }

    try {
        const providerKey = await providerKeyGate.providerKeyManager.getProviderKey(providerKeyId)
        if (!providerKey) {
            return 'provider_key_not_found'
        }
        if (providerKey.team_id !== definition.team_id) {
            return 'provider_key_team_mismatch'
        }
        if (providerKey.state !== 'ok') {
            return 'provider_key_not_ok'
        }
    } catch (error) {
        logger.error('Provider key gate failed open', {
            definitionId: definition.id,
            providerKeyId,
            error: error instanceof Error ? error.message : String(error),
        })
    }

    return null
}
