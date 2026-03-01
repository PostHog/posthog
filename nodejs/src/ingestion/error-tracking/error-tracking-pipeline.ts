import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/kafka/producer'
import { EventIngestionRestrictionManager } from '~/utils/event-ingestion-restrictions'
import { GeoIp } from '~/utils/geoip'
import { PromiseScheduler } from '~/utils/promise-scheduler'
import { TeamManager } from '~/utils/team-manager'
import { GroupTypeManager } from '~/worker/ingestion/group-type-manager'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import {
    createApplyEventRestrictionsStep,
    createOverflowLaneTTLRefreshStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createRateLimitToOverflowStep,
    createResolveTeamStep,
} from '../event-preprocessing'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '../pipelines/builders'
import { TopHogRegistry, count, countResult, createTopHogWrapper, timer } from '../pipelines/extensions/tophog'
import { createBatch, createUnwrapper } from '../pipelines/helpers'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { createCymbalProcessingStep } from './cymbal-processing-step'
import { CymbalClient } from './cymbal/client'
import { createGeoIPEnrichmentStep } from './geoip-enrichment-step'
import { createGroupTypeMappingStep } from './group-type-mapping-step'
import { createPersonPropertiesReadOnlyStep } from './person-properties-step'
import { createErrorTrackingPrepareEventStep } from './prepare-event-step'

export interface ErrorTrackingPipelineInput {
    message: Message
}

/**
 * The pipeline output is void because the final step emits to Kafka.
 * Successful events are produced to the output topic, while failures
 * are handled by the result handling pipeline (DLQ, drop, redirect).
 */
export type ErrorTrackingPipelineOutput = void

export interface ErrorTrackingPipelineConfig {
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    outputTopic: string
    groupId: string
    promiseScheduler: PromiseScheduler
    teamManager: TeamManager
    personRepository: PersonRepository
    geoip: GeoIp
    cymbalClient: CymbalClient
    groupTypeManager: GroupTypeManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    /** Producer for ingestion warnings. */
    ingestionWarningProducer: KafkaProducerWrapper
    /** Service for rate limiting and redirecting to overflow (main lane only). */
    overflowRedirectService?: OverflowRedirectService
    /** Service for refreshing TTLs on overflow lane events. */
    overflowLaneTTLRefreshService?: OverflowRedirectService
    /** TopHog registry for metrics. */
    topHog: TopHogRegistry
}

/**
 * Creates the error tracking pipeline.
 *
 * The pipeline processes exception events through these phases:
 * 1. Parse headers - Extract token, timestamps from Kafka message headers
 * 2. Apply event restrictions - Billing limits, drop/overflow
 * 3. Parse Kafka message - Parse message body into event
 * 4. Resolve team - Look up team by token
 * 5. Cymbal processing - Symbolicate, fingerprint, and link issues
 * 6. Person properties - Fetch person by distinct_id (read-only)
 * 7. GeoIP enrichment - Enrich with geographic data based on IP
 * 8. Group type mapping - Map group types to indexes
 * 9. Prepare event - Convert to PreIngestionEvent format, track if person found
 * 10. Create event - Build ErrorTrackingKafkaEvent (matches Cymbal's output format)
 * 11. Emit event - Produce to output topic
 *
 * Note: Cymbal runs before enrichment because it only needs the raw exception data
 * for symbolication and fingerprinting. This reduces payload size and avoids
 * wasted enrichment work if Cymbal suppresses the event.
 */
export function createErrorTrackingPipeline(
    config: ErrorTrackingPipelineConfig
): BatchPipelineUnwrapper<ErrorTrackingPipelineInput, ErrorTrackingPipelineOutput, { message: Message }> {
    const {
        kafkaProducer,
        dlqTopic,
        outputTopic,
        groupId,
        promiseScheduler,
        teamManager,
        personRepository,
        geoip,
        cymbalClient,
        groupTypeManager,
        eventIngestionRestrictionManager,
        overflowEnabled,
        overflowTopic,
        ingestionWarningProducer,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        topHog,
    } = config

    const topHogWrapper = createTopHogWrapper(topHog)

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const pipeline = newBatchPipelineBuilder<ErrorTrackingPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    b
                        // Parse headers from Kafka message [REUSE]
                        .pipe(createParseHeadersStep())
                        // Apply event restrictions (billing limits, drop/overflow) [REUSE]
                        .pipe(
                            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                overflowEnabled,
                                overflowTopic,
                                preservePartitionLocality: false,
                            })
                        )
                        // Parse Kafka message body [REUSE]
                        .pipe(createParseKafkaMessageStep())
                        // Resolve team from token [REUSE]
                        .pipe(
                            topHogWrapper(createResolveTeamStep(teamManager), [
                                countResult('resolved_teams', (output) => ({
                                    team_id: String(output.team.id),
                                })),
                            ])
                        )
                )
                // Map team to context for handleIngestionWarnings
                .filterMap(
                    (element) => ({
                        result: element.result,
                        context: {
                            ...element.context,
                            team: { id: element.result.value.team.id },
                        },
                    }),
                    (b) =>
                        b
                            .teamAware((b) =>
                                b
                                    .gather()
                                    // Rate limit high-volume token:distinct_id pairs to overflow
                                    .pipeBatch(
                                        createRateLimitToOverflowStep(
                                            overflowTopic,
                                            false, // preservePartitionLocality
                                            overflowRedirectService
                                        )
                                    )
                                    // Refresh TTLs for overflow lane events (keeps Redis flags alive)
                                    .pipeBatch(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
                                    // Process through Cymbal as a batch (before enrichment - Cymbal only
                                    // needs raw exception data, not person/geoip/group data)
                                    .pipeBatch(createCymbalProcessingStep(cymbalClient))
                                    // Enrich, prepare, create, and emit events
                                    .sequentially((b) =>
                                        b
                                            // Fetch person properties (read-only, no updates)
                                            .pipe(
                                                topHogWrapper(createPersonPropertiesReadOnlyStep(personRepository), [
                                                    timer('person_lookup_time', (input) => ({
                                                        team_id: String(input.team.id),
                                                        distinct_id: input.event.distinct_id,
                                                    })),
                                                ])
                                            )
                                            // Enrich with GeoIP data
                                            .pipe(createGeoIPEnrichmentStep(geoip))
                                            // Map group types to indexes
                                            .pipe(createGroupTypeMappingStep(groupTypeManager))
                                            // Prepare event for emission
                                            .pipe(createErrorTrackingPrepareEventStep())
                                            .pipe(createCreateEventStep())
                                            .pipe(
                                                topHogWrapper(
                                                    createEmitEventStep({
                                                        kafkaProducer,
                                                        clickhouseJsonEventsTopic: outputTopic,
                                                        groupId,
                                                    }),
                                                    [
                                                        count('emitted_events', (input) => ({
                                                            team_id: String(input.eventToEmit.team_id),
                                                        })),
                                                        count('emitted_events_per_distinct_id', (input) => ({
                                                            team_id: String(input.eventToEmit.team_id),
                                                            distinct_id: input.eventToEmit.distinct_id,
                                                        })),
                                                    ]
                                                )
                                            )
                                    )
                            )
                            .handleIngestionWarnings(ingestionWarningProducer)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
        .gather()
        .build()

    return createUnwrapper(pipeline)
}

/**
 * Runs a batch of messages through the error tracking pipeline.
 *
 * Events are emitted to the output topic as a side effect. Failures are
 * handled by the result handling pipeline (DLQ, drop, redirect).
 */
export async function runErrorTrackingPipeline(
    pipeline: BatchPipelineUnwrapper<ErrorTrackingPipelineInput, ErrorTrackingPipelineOutput, { message: Message }>,
    messages: Message[]
): Promise<void> {
    if (messages.length === 0) {
        return
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    pipeline.feed(batch)

    while ((await pipeline.next()) !== null) {
        // Drain all results
    }
}
