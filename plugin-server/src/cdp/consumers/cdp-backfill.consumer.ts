import { randomUUID } from 'crypto'
import { Message } from 'node-rdkafka'
import { compress } from 'snappy'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_CDP_BACKFILL_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { HogInputsService } from '../services/hog-inputs.service'
import { serializeInvocation } from '../services/job-queue/job-queue-kafka'
import { cdpJobSizeKb } from '../services/job-queue/shared'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationHogFunctionContext,
    CyclotronJobInvocationResult,
} from '../types'
import {
    getPersonDisplayName,
    isLegacyPluginHogFunction,
    isNativeHogFunction,
    isSegmentPluginHogFunction,
} from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'

export type BackfillEvent = RawClickHouseEvent & {
    batch_export_id: string
}

export class CdpBackfillConsumer extends CdpConsumerBase {
    protected name = 'CdpBackfillConsumer'
    private kafkaConsumer: KafkaConsumer
    private topic: string
    private hogInputsService: HogInputsService

    constructor(hub: Hub, topic: string = KAFKA_CDP_BACKFILL_EVENTS, groupId: string = 'cdp-backfill-consumer') {
        super(hub)
        this.topic = topic
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
        this.hogInputsService = new HogInputsService(hub)
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    private async parseKafkaBatch(messages: Message[]): Promise<CyclotronJobInvocationHogFunction[]> {
        const invocations: CyclotronJobInvocationHogFunction[] = []

        // Group messages by team_id and batch_export_id for efficient lookups
        const eventsByTeam = new Map<number, BackfillEvent[]>()
        const batchExportIds = new Set<string>()

        for (const message of messages) {
            try {
                const event = parseJSON(message.value!.toString()) as BackfillEvent

                if (!eventsByTeam.has(event.team_id)) {
                    eventsByTeam.set(event.team_id, [])
                }
                eventsByTeam.get(event.team_id)!.push(event)
                batchExportIds.add(event.batch_export_id)
            } catch (e) {
                logger.error('Error parsing backfill message', { error: e })
            }
        }

        // Fetch teams and hog functions in parallel
        const teamIds = Array.from(eventsByTeam.keys())
        const batchExportIdArray = Array.from(batchExportIds)

        const [teams, hogFunctions] = await Promise.all([
            Promise.all(
                teamIds.map(async (teamId) => {
                    const team = await this.hub.teamManager.getTeamForEvent({ team_id: teamId })
                    return { teamId, team }
                })
            ),
            Promise.all(
                batchExportIdArray.map(async (batchExportId) => {
                    const hogFunction = await this.hogFunctionManager.getHogFunctionByBatchExportId(batchExportId)
                    return { batchExportId, hogFunction }
                })
            ),
        ])

        const teamMap = new Map(teams.map(({ teamId, team }) => [teamId, team]))
        const hogFunctionMap = new Map(
            hogFunctions.map(({ batchExportId, hogFunction }) => [batchExportId, hogFunction])
        )

        // Convert events to invocations
        for (const [teamId, teamEvents] of eventsByTeam.entries()) {
            const team = teamMap.get(teamId)
            if (!team) {
                logger.error('⚠️', 'Team not found for backfill events', {
                    teamId,
                    eventCount: teamEvents.length,
                })
                continue
            }

            for (const event of teamEvents) {
                try {
                    const hogFunction = hogFunctionMap.get(event.batch_export_id)
                    if (!hogFunction) {
                        logger.error('⚠️', 'Hog function not found for batch_export_id', {
                            batchExportId: event.batch_export_id,
                            teamId: event.team_id,
                        })
                        continue
                    }

                    if (!hogFunction.enabled || hogFunction.deleted) {
                        logger.info('⚠️', 'Skipping event due to hog function being deleted or disabled', {
                            batchExportId: event.batch_export_id,
                            functionId: hogFunction.id,
                        })
                        continue
                    }

                    // Validate required fields on event
                    if (!event.uuid || !event.event || !event.distinct_id) {
                        logger.error('⚠️', 'Backfill event missing required fields', {
                            batchExportId: event.batch_export_id,
                            teamId: event.team_id,
                            hasUuid: !!event.uuid,
                            hasEvent: !!event.event,
                            hasDistinctId: !!event.distinct_id,
                            eventKeys: Object.keys(event),
                        })
                        continue
                    }

                    // Convert backfill event to invocation globals
                    // Backfill events have properties as objects (not JSON strings like ClickHouse events)
                    const properties = (event.properties as any) ?? {}
                    const projectUrl = `${this.hub.SITE_URL ?? 'http://localhost:8010'}/project/${team.id}`

                    let person
                    if (event.person_id) {
                        const personProperties = (event.person_properties as any) ?? {}
                        const personDisplayName = getPersonDisplayName(team, event.distinct_id, personProperties)

                        person = {
                            id: event.person_id,
                            properties: personProperties,
                            name: personDisplayName,
                            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
                        }
                    }

                    const globals = {
                        project: {
                            id: team.id,
                            name: team.name,
                            url: projectUrl,
                        },
                        event: {
                            uuid: event.uuid,
                            event: event.event!,
                            elements_chain: event.elements_chain,
                            distinct_id: event.distinct_id,
                            properties,
                            timestamp: event.timestamp,
                            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(event.timestamp)}`,
                        },
                        person,
                    }

                    // Build inputs using HogInputsService to properly execute bytecode
                    const globalsWithInputs = await this.hogInputsService.buildInputsWithGlobals(hogFunction, globals)

                    // Create initial state for the invocation
                    const state: CyclotronJobInvocationHogFunctionContext = {
                        globals: globalsWithInputs,
                        timings: [],
                        attempts: 0,
                    }

                    // Create the invocation with hog function attached
                    const invocation: CyclotronJobInvocationHogFunction = {
                        id: randomUUID(),
                        teamId: event.team_id,
                        functionId: hogFunction.id,
                        state,
                        queue: 'hog',
                        queuePriority: 0,
                        hogFunction,
                    }

                    invocations.push(invocation)
                } catch (e) {
                    logger.error('Error converting backfill event to invocation', {
                        error: String(e),
                        errorMessage: e instanceof Error ? e.message : String(e),
                        errorStack: e instanceof Error ? e.stack : undefined,
                        teamId: event.team_id,
                        batchExportId: event.batch_export_id,
                        eventKeys: Object.keys(event),
                    })
                    captureException(e)
                }
            }
        }

        return invocations
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public async processInvocations(
        invocations: CyclotronJobInvocationHogFunction[]
    ): Promise<CyclotronJobInvocationResult[]> {
        return await Promise.all(
            invocations.map((item) => {
                if (isNativeHogFunction(item.hogFunction)) {
                    return this.nativeDestinationExecutorService.execute(item)
                } else if (isLegacyPluginHogFunction(item.hogFunction)) {
                    return this.pluginDestinationExecutorService.execute(item)
                } else if (isSegmentPluginHogFunction(item.hogFunction)) {
                    return this.segmentDestinationExecutorService.execute(item)
                } else {
                    return this.hogExecutor.executeWithAsyncFunctions(item)
                }
            })
        )
    }

    public async processBatch(
        invocations: CyclotronJobInvocationHogFunction[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        const invocationResults = await this.processInvocations(invocations)

        // NOTE: We queue results back for retries and async operations, then publish metrics in background
        const backgroundTask = this.queueInvocationResults(invocationResults).then(() => {
            // NOTE: After this point we parallelize and any issues are logged rather than thrown as retrying now would end up in duplicate messages
            return Promise.allSettled([
                this.hogFunctionMonitoringService
                    .queueInvocationResults(invocationResults)
                    .then(() => this.hogFunctionMonitoringService.flush())
                    .catch((err) => {
                        captureException(err)
                        logger.error('Error processing invocation results', { err })
                    }),
                this.hogWatcher.observeResults(invocationResults).catch((err: any) => {
                    captureException(err)
                    logger.error('Error observing results', { err })
                }),
            ])
        })

        return { backgroundTask, invocationResults }
    }

    protected async queueInvocationResults(invocations: CyclotronJobInvocationResult[]) {
        // Queue unfinished invocations back to the backfill topic for retries
        const unfinishedInvocations = invocations.filter((x) => !x.finished)

        if (unfinishedInvocations.length === 0 || !this.kafkaProducer) {
            return
        }

        await Promise.all(
            unfinishedInvocations.map(async (result) => {
                const invocation = result.invocation
                const serialized = serializeInvocation(invocation)

                const value = this.hub.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA
                    ? await compress(JSON.stringify(serialized))
                    : JSON.stringify(serialized)

                cdpJobSizeKb.observe(value.length / 1024)

                const headers: Record<string, string> = {
                    functionId: invocation.functionId,
                    teamId: invocation.teamId.toString(),
                }

                if (invocation.queueScheduledAt) {
                    headers.queueScheduledAt = invocation.queueScheduledAt.toString()
                }

                await this.kafkaProducer!.produce({
                    value: Buffer.from(value),
                    key: Buffer.from(invocation.id),
                    topic: this.topic,
                    headers,
                }).catch((e) => {
                    logger.error('🔄', 'Error producing backfill kafka message', {
                        error: String(e),
                        teamId: invocation.teamId,
                        functionId: invocation.functionId,
                        payloadSizeKb: value.length / 1024,
                    })

                    throw e
                })
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const invocations = await this.parseKafkaBatch(messages)
                const { backgroundTask, invocationResults } = await this.processBatch(invocations)

                return { backgroundTask, invocationResults }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('🔄', 'Stopping backfill consumer')
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
