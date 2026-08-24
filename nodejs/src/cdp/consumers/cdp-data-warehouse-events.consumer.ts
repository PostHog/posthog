import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { HealthCheckResult, PluginsServerConfig, Team } from '../../types'
import { CdpDataWarehouseEvent, CdpDataWarehouseEventSchema } from '../schema'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import {
    CyclotronJobInvocation,
    HogFunctionFilterDataWarehouse,
    HogFunctionInvocationGlobals,
    HogFunctionTypeType,
} from '../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

// Synthetic event name stamped on the synthetic event built for a warehouse-row trigger.
// Acts as the "this globals object originated from a synced warehouse row" discriminator.
export const WAREHOUSE_SOURCE_ROW_EVENT = '$warehouse_source_row'

// The same, for a row a materialized view run added or updated. Kept distinct from the source-table
// name so a run's origin is legible in logs and test payloads without decoding the trigger config.
export const WAREHOUSE_VIEW_ROW_EVENT = '$warehouse_view_row'

// Filter source / trigger type each kind of warehouse row matches against.
const TRIGGER_TYPE_BY_TABLE_TYPE = {
    source: 'data-warehouse-table',
    view: 'data-warehouse-view',
} as const

type WarehouseTableType = keyof typeof TRIGGER_TYPE_BY_TABLE_TYPE

const WAREHOUSE_TRIGGER_TYPES = new Set<string>(Object.values(TRIGGER_TYPE_BY_TABLE_TYPE))

// Special property on the synthetic event holding the dot-notated source table name.
// Used by the pipeline's eligibility predicate to match warehouse-table HogFlow triggers
// against the row's source table without adding a top-level field to globals.
export const DWH_SOURCE_TABLE_PROPERTY = '$source_table'

export class CdpDatawarehouseEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpDatawarehouseEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    protected hogQueue: JobQueue
    protected hogflowQueue: JobQueue
    protected kafkaConsumer: KafkaConsumerInterface
    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue }
    ) {
        super(config, deps)
        this.hogQueue = jobQueues.hogQueue
        this.hogflowQueue = jobQueues.hogflowQueue
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-data-warehouse-events-consumer',
            topic: 'cdp_data_warehouse_source_table',
        })
        this.hogFunctionPipeline = new HogFunctionInvocationPipeline(config, {
            hogFunctionManager: this.hogFunctionManager,
            hogInputsService: this.hogInputsService,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
        })
        this.hogFlowPipeline = new HogFlowInvocationPipeline(config, {
            hogFlowManager: this.hogFlowManager,
            hogFlowExecutor: this.hogFlowExecutor,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
        })
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (!invocationGlobals.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        // Warehouse rows carry no `$groups` property — group enrichment is a no-op here, so we skip the
        // call entirely to avoid the per-batch group-types lookup.

        const [hogInvocations, hogflowInvocations] = await Promise.all([
            this.hogFunctionPipeline.buildInvocations(invocationGlobals, {
                hogTypes: this.hogTypes,
                filterFn: (fn) => WAREHOUSE_TRIGGER_TYPES.has(fn.filters?.source ?? 'events'),
                // Destinations pick their tables in `filters.data_warehouse`, which never reaches the
                // filter bytecode, so without this every warehouse-triggered destination in the team
                // ran for every table's rows.
                invocationFilterFn: (fn, globals) =>
                    fn.filters?.source === triggerTypeOf(globals) &&
                    matchesSubscribedTable(fn.filters?.data_warehouse, sourceTableOf(globals)),
            }),
            // Source-compatibility matching lives in the consumer rather than the executor — the
            // consumer knows it's serving warehouse rows, so it filters flows to only those whose
            // trigger matches the row's kind and $source_table property. The executor then just
            // evaluates filter bytecode on the matched flows.
            this.hogFlowPipeline.buildInvocations(invocationGlobals, {
                eligibilityFn: (flow, globals) =>
                    (flow.trigger.type === 'data-warehouse-table' || flow.trigger.type === 'data-warehouse-view') &&
                    flow.trigger.type === triggerTypeOf(globals) &&
                    flow.trigger.table_name === sourceTableOf(globals),
            }),
        ])

        const invocationsToBeQueued = [...hogInvocations, ...hogflowInvocations]

        // Emit a `running` lifecycle row for each freshly-created invocation so the runs UI shows
        // warehouse-triggered flows as in-flight (matching the event consumer). The terminal row is
        // queued later by the cyclotron worker; both collapse under the same `invocation_id` via
        // ReplacingMergeTree, with the terminal row's later `version` superseding the running row.
        for (const invocation of invocationsToBeQueued) {
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        return {
            backgroundTask: Promise.all([
                instrumentFn({ key: 'cdp.background_task.queue_hog_invocations', sendException: false }, () =>
                    this.hogQueue.queueInvocations(hogInvocations)
                ),
                instrumentFn({ key: 'cdp.background_task.queue_hogflow_invocations', sendException: false }, () =>
                    this.hogflowQueue.queueInvocations(hogflowInvocations)
                ),
                instrumentFn({ key: 'cdp.background_task.monitoring_flush', sendException: false }, async () => {
                    try {
                        await this.hogFunctionMonitoringService.flush()
                    } catch (err) {
                        captureException(err)
                        logger.error('🔴', 'Error producing queued messages for monitoring', { err })
                    }
                }),
                instrumentFn({ key: 'cdp.background_task.lifecycle_running_flush', sendException: false }, () =>
                    this.invocationResultsService.invocationResultsRowsService.flush()
                ),
            ]),
            invocations: invocationsToBeQueued,
        }
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const kafkaEvent = parseJSON(message.value!.toString()) as unknown
                    const event = CdpDataWarehouseEventSchema.parse(kafkaEvent)

                    const [teamHogFunctions, teamHogFlows, team] = await Promise.all([
                        this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, this.hogTypes),
                        this.hogFlowManager.getHogFlowsForTeam(event.team_id),
                        this.deps.teamManager.getTeam(event.team_id),
                    ])

                    if ((!teamHogFunctions.length && !teamHogFlows.length) || !team) {
                        return
                    }

                    events.push(
                        convertDataWarehouseEventToHogFunctionInvocationGlobals(event, team, this.config.SITE_URL)
                    )
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    public override async start(): Promise<void> {
        await super.start()
        await Promise.all([this.hogQueue.startAsProducer(), this.hogflowQueue.startAsProducer()])
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, { size: messages.length })
            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(invocationGlobals)
                return { backgroundTask }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        await Promise.all([this.hogQueue.stopProducer(), this.hogflowQueue.stopProducer()])
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

/**
 * Which trigger a row's globals can match. The synthetic event name is the discriminator, so the
 * row's own properties stay exactly what the warehouse produced.
 */
function triggerTypeOf(globals: HogFunctionInvocationGlobals): string {
    return globals.event?.event === WAREHOUSE_VIEW_ROW_EVENT
        ? TRIGGER_TYPE_BY_TABLE_TYPE.view
        : TRIGGER_TYPE_BY_TABLE_TYPE.source
}

function sourceTableOf(globals: HogFunctionInvocationGlobals): string {
    const table = globals.event?.properties?.[DWH_SOURCE_TABLE_PROPERTY]
    return typeof table === 'string' ? table : ''
}

/**
 * An empty or absent subscription list keeps the pre-existing "match every table" behavior.
 * Destinations saved before per-table matching existed have no entries, and tightening them here
 * would silently stop them firing.
 */
function matchesSubscribedTable(
    subscriptions: HogFunctionFilterDataWarehouse[] | undefined,
    sourceTable: string
): boolean {
    if (!subscriptions?.length) {
        return true
    }
    return subscriptions.some((subscription) => subscription.table_name === sourceTable)
}

function convertDataWarehouseEventToHogFunctionInvocationGlobals(
    event: CdpDataWarehouseEvent,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const data = event.properties
    const projectUrl = `${siteUrl}/project/${team.id}`

    // The synthetic event carries:
    //   - the producer's deterministic per-row id (CDPProducer._build_event_id) as the uuid, so
    //     billing dedup (keyed on event.uuid) counts each row distinctly and stably across re-runs
    //   - `$warehouse_source_row` or `$warehouse_view_row` as the event name, which both identifies
    //     warehouse-row globals and says which trigger kind they can match
    //   - the source table name on `properties.$source_table` so consumers can match warehouse
    //     triggers without a new top-level field on globals
    const tableType: WarehouseTableType = event.table_type ?? 'source'

    return {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: event.event_id,
            event: tableType === 'view' ? WAREHOUSE_VIEW_ROW_EVENT : WAREHOUSE_SOURCE_ROW_EVENT,
            elements_chain: '', // Not applicable but left here for compatibility
            distinct_id: 'data-warehouse-table-distinct-id-do-not-use',
            properties: {
                ...data,
                [DWH_SOURCE_TABLE_PROPERTY]: event.table_name ?? '',
            },
            timestamp: DateTime.now().toISO(),
            url: '',
        },
    }
}
