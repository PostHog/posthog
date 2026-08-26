import { Counter, Gauge } from 'prom-client'

import { HogTransformationResult, HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { GeoIPService, GeoIp } from '~/common/utils/geoip'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { PluginEvent } from '~/plugin-scaffold'

import { CyclotronJobInvocationResult, HogFunctionInvocationGlobals, HogFunctionType } from '../../cdp/types'
import { isLegacyPluginHogFunction } from '../../cdp/utils'
import type { CommonConfig } from '../../common/config'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogInputsService } from '../services/hog-inputs.service'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { IntegrationManagerService } from '../services/managers/integration-manager.service'
import { HogFunctionMonitoringService, MonitoringOutput } from '../services/monitoring/hog-function-monitoring.service'
import { EncryptedFields } from '../utils/encryption-utils'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation } from '../utils/invocation-utils'
import { RustVmExecutor } from './rust-vm-executor'
import { getTransformationFunctions } from './transformation-functions'

export interface HogTransformerConfig {
    siteUrl: string
    hogRustVmExecutionEnabled: boolean
    mmdbFileLocation: string
}

export const hogTransformationDroppedEvents = new Counter({
    name: 'hog_transformation_dropped_events',
    help: 'Indicates how many events are dropped by hog transformations',
})

export const hogTransformationInvocations = new Counter({
    name: 'hog_transformation_invocations_total',
    help: 'Number of times transformEvent was called directly',
})

export const hogTransformationAttempts = new Counter({
    name: 'hog_transformation_attempts_total',
    help: 'Number of transformation attempts before any processing',
    labelNames: ['type'],
})

export const hogTransformationCompleted = new Counter({
    name: 'hog_transformation_completed_total',
    help: 'Number of successfully completed transformations',
    labelNames: ['type'],
})

export const hogTransformationPendingInvocationResults = new Gauge({
    name: 'hog_transformation_pending_invocation_results',
    help: 'Number of invocation results accumulated and waiting to be processed. High values indicate memory accumulation.',
})

export const hogTransformationUnexpectedErrors = new Counter({
    name: 'hog_transformation_unexpected_errors_total',
    help: 'Number of unexpected errors during transformation execution. Any occurrence should trigger an alert as the transformation is skipped.',
})

export interface TransformationResult extends HogTransformationResult {
    event: PluginEvent | null
    invocationResults: CyclotronJobInvocationResult[]
}

export class HogTransformerService implements HogTransformer {
    private invocationResults: CyclotronJobInvocationResult[] = []
    private cachedGeoIp?: GeoIp
    private cachedTransformationFunctions?: ReturnType<typeof getTransformationFunctions>
    private rustVmExecutor: RustVmExecutor | null

    constructor(
        private hogFunctionManager: HogFunctionManagerService,
        private hogExecutor: HogExecutorService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService,
        private pluginExecutor: LegacyPluginExecutorService,
        private geoipService: GeoIPService,
        private config: HogTransformerConfig
    ) {
        this.rustVmExecutor = config.hogRustVmExecutionEnabled
            ? new RustVmExecutor({ mmdbPath: config.mmdbFileLocation })
            : null
    }

    public async start(): Promise<void> {}

    public async stop(): Promise<void> {
        await this.processInvocationResults()
    }

    public async processInvocationResults(): Promise<void> {
        const results = [...this.invocationResults]
        this.invocationResults = []
        hogTransformationPendingInvocationResults.set(0)

        this.hogFunctionMonitoringService.queueInvocationResults(results)

        await this.hogFunctionMonitoringService.flush()
    }

    private async getTransformationFunctions() {
        if (!this.cachedTransformationFunctions) {
            this.cachedGeoIp = await this.geoipService.get()
            this.cachedTransformationFunctions = getTransformationFunctions(this.cachedGeoIp)
        }
        return this.cachedTransformationFunctions
    }

    private createInvocationGlobals(event: PluginEvent): HogFunctionInvocationGlobals {
        return {
            project: {
                id: event.team_id,
                name: '',
                url: this.config.siteUrl,
            },
            event: {
                uuid: event.uuid,
                event: event.event,
                distinct_id: event.distinct_id,
                properties: event.properties || {},
                elements_chain: event.properties?.$elements_chain || '',
                timestamp: event.timestamp || '',
                url: event.properties?.$current_url || '',
            },
        }
    }

    private async transformEventAndProduceMessagesImpl(event: PluginEvent): Promise<TransformationResult> {
        hogTransformationAttempts.inc({ type: 'with_messages' })

        const teamHogFunctions = await this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, ['transformation'])

        const transformationResult = await this.transformEvent(event, teamHogFunctions)

        for (const result of transformationResult.invocationResults) {
            this.invocationResults.push(result)
        }
        hogTransformationPendingInvocationResults.set(this.invocationResults.length)

        hogTransformationCompleted.inc({ type: 'with_messages' })
        return {
            ...transformationResult,
        }
    }

    public transformEventAndProduceMessages(event: PluginEvent): Promise<TransformationResult> {
        return instrumentFn(`hogTransformer.transformEventAndProduceMessages`, () =>
            this.transformEventAndProduceMessagesImpl(event)
        )
    }

    private async transformEventImpl(
        event: PluginEvent,
        teamHogFunctions: HogFunctionType[]
    ): Promise<TransformationResult> {
        hogTransformationInvocations.inc()

        // Early return if no transformations to run
        if (teamHogFunctions.length === 0) {
            return {
                event,
                invocationResults: [],
            }
        }

        const results: CyclotronJobInvocationResult[] = []

        // Create globals once and update the event properties after each transformation
        const globals = this.createInvocationGlobals(event)

        for (const hogFunction of teamHogFunctions) {
            // Create filterGlobals for each iteration - it references globals.event.properties
            // which gets updated after each successful transformation
            const filterGlobals = convertToHogFunctionFilterGlobal(globals)

            // Check if function has filters - if not, always apply
            if (hogFunction.filters?.bytecode) {
                const filterResults = await filterFunctionInstrumented({
                    fn: hogFunction,
                    filters: hogFunction.filters,
                    filterGlobals,
                })

                // If filter didn't pass skip the actual transformation and add logs and errors from the filterResult
                this.hogFunctionMonitoringService.queueAppMetrics(filterResults.metrics, 'hog_function')
                this.hogFunctionMonitoringService.queueLogs(filterResults.logs, 'hog_function')

                if (!filterResults.match) {
                    continue
                }
            }

            let result: CyclotronJobInvocationResult
            try {
                result = await this.executeHogFunction(hogFunction, globals)
            } catch (err) {
                hogTransformationUnexpectedErrors.inc()
                logger.error('⚠️', 'Unexpected error executing transformation', {
                    function_id: hogFunction.id,
                    team_id: event.team_id,
                    error: String(err),
                })
                this.hogFunctionMonitoringService.queueAppMetric(
                    {
                        team_id: event.team_id,
                        app_source_id: hogFunction.id,
                        metric_kind: 'failure',
                        metric_name: 'failed',
                        count: 1,
                    },
                    'hog_function'
                )
                continue
            }

            results.push(result)

            if (result.error) {
                continue
            }

            if (!result.execResult) {
                hogTransformationDroppedEvents.inc()
                this.hogFunctionMonitoringService.queueAppMetric(
                    {
                        team_id: event.team_id,
                        app_source_id: hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'dropped',
                        count: 1,
                    },
                    'hog_function'
                )
                return {
                    event: null,
                    invocationResults: results,
                    droppedBy: { id: hogFunction.id, name: hogFunction.name },
                }
            }

            const transformedEvent: unknown = result.execResult

            if (
                !transformedEvent ||
                typeof transformedEvent !== 'object' ||
                !('properties' in transformedEvent) ||
                !transformedEvent.properties ||
                typeof transformedEvent.properties !== 'object'
            ) {
                logger.error('⚠️', 'Invalid transformation result - missing or invalid properties', {
                    function_id: hogFunction.id,
                })
                continue
            }

            event.properties = transformedEvent.properties as Record<string, any>
            event.ip = event.properties.$ip ?? null

            if ('event' in transformedEvent) {
                if (typeof transformedEvent.event !== 'string') {
                    logger.error('⚠️', 'Invalid transformation result - event name must be a string', {
                        function_id: hogFunction.id,
                        event: transformedEvent.event,
                    })
                    continue
                }
                event.event = transformedEvent.event
            }

            if ('distinct_id' in transformedEvent) {
                if (typeof transformedEvent.distinct_id !== 'string') {
                    logger.error('⚠️', 'Invalid transformation result - distinct_id must be a string', {
                        function_id: hogFunction.id,
                        distinct_id: transformedEvent.distinct_id,
                    })
                    continue
                }
                event.distinct_id = transformedEvent.distinct_id
            }

            // Update globals so the next transformation sees the changes
            globals.event.properties = event.properties
            globals.event.event = event.event
            globals.event.distinct_id = event.distinct_id
        }

        return {
            event,
            invocationResults: results,
        }
    }

    public transformEvent(event: PluginEvent, teamHogFunctions: HogFunctionType[]): Promise<TransformationResult> {
        // These properties are retired, so drop any a client sends rather than letting them through
        if (event.properties) {
            for (const key of ['$transformations_failed', '$transformations_skipped', '$transformations_succeeded']) {
                if (key in event.properties) {
                    delete event.properties[key]
                }
            }
        }

        return instrumentFn(`hogTransformer.transformEvent`, () => this.transformEventImpl(event, teamHogFunctions))
    }

    private async executeHogFunction(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<CyclotronJobInvocationResult> {
        const transformationFunctions = await this.getTransformationFunctions()
        const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)

        const invocation = createInvocation(globalsWithInputs, hogFunction)

        if (isLegacyPluginHogFunction(hogFunction)) {
            return await this.pluginExecutor.execute(invocation)
        }

        if (this.rustVmExecutor) {
            const sensitiveValues = this.hogExecutor.getSensitiveValues(hogFunction, globalsWithInputs.inputs)
            const rustResult = this.rustVmExecutor.execute(invocation, sensitiveValues)
            // Null means the Rust VM can't run this program (addon not built, unsupported host
            // function): fall through to the Node VM.
            if (rustResult) {
                return rustResult
            }
        }

        return await this.hogExecutor.execute(invocation, { functions: transformationFunctions })
    }
}

/** Config read by createHogTransformerService when running inside ingestion. */
export type HogTransformerServiceConfig = Pick<
    CommonConfig,
    'SITE_URL' | 'CDP_HOG_RUST_VM_EXECUTION_ENABLED' | 'MMDB_FILE_LOCATION' | 'TRANSFORMATIONS_HOG_TIMEOUT_MS'
>

export interface HogTransformerServiceDeps {
    geoipService: GeoIPService
    postgres: PostgresRouter
    pubSub: PubSub
    encryptedFields: EncryptedFields
    integrationManager: IntegrationManagerService
    monitoringOutputs: IngestionOutputs<MonitoringOutput>
}

/**
 * Keep this factory's config and dependencies intentionally minimal. Transformations run only the synchronous Hog
 * execution core and must not inherit Redis, fetch, email, push, or other CDP delivery infrastructure just to satisfy
 * a shared service constructor. Anything that needs those belongs in HogExecutorAsyncService, not in HogExecutorService.
 */
export function createHogTransformerService(
    config: HogTransformerServiceConfig,
    deps: HogTransformerServiceDeps
): HogTransformerService {
    const hogFunctionManager = new HogFunctionManagerService(deps.postgres, deps.pubSub, deps.encryptedFields)
    const hogInputsService = new HogInputsService(deps.integrationManager, undefined, deps.encryptedFields)
    const hogExecutor = new HogExecutorService(
        { executionTimeoutMs: config.TRANSFORMATIONS_HOG_TIMEOUT_MS },
        hogInputsService
    )
    const pluginExecutor = new LegacyPluginExecutorService(deps.postgres, deps.geoipService)
    const hogFunctionMonitoringService = new HogFunctionMonitoringService(deps.monitoringOutputs)
    return new HogTransformerService(
        hogFunctionManager,
        hogExecutor,
        hogFunctionMonitoringService,
        pluginExecutor,
        deps.geoipService,
        {
            siteUrl: config.SITE_URL,
            hogRustVmExecutionEnabled: config.CDP_HOG_RUST_VM_EXECUTION_ENABLED,
            mmdbFileLocation: config.MMDB_FILE_LOCATION,
        }
    )
}
