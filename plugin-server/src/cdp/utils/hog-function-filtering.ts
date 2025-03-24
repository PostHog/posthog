import { ExecResult } from '@posthog/hogvm'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import { execHog } from '../services/hog-executor.service'
import {
    HogFunctionAppMetric,
    HogFunctionFilterGlobals,
    HogFunctionInvocationLogEntry,
    HogFunctionType,
} from '../types'

const hogFunctionFilterDuration = new Histogram({
    name: 'cdp_hog_function_filter_duration_ms',
    help: 'Processing time for filtering a function',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
    labelNames: ['type'],
})

interface HogFunctionFilterResult {
    match: boolean
    error?: unknown
    logs: HogFunctionInvocationLogEntry[]
    metrics: HogFunctionAppMetric[]
}

/**
 * Shared utility to check if an event matches the filters of a HogFunction.
 * Used by both the HogExecutorService (for destinations) and HogTransformerService (for transformations).
 */
export function checkHogFunctionFilters(options: {
    hogFunction: HogFunctionType
    filterGlobals: HogFunctionFilterGlobals
    /** Optional filters to use instead of those on the function */
    filters?: HogFunctionType['filters']
    /** Whether to enable telemetry for this function at the hogvm level */
    enabledTelemetry?: boolean
    /** The event UUID to use for logging */
    eventUuid?: string
}): HogFunctionFilterResult {
    const { hogFunction, filterGlobals, enabledTelemetry, eventUuid } = options
    const filters = options.filters ?? hogFunction.filters
    const start = performance.now()
    const logs: HogFunctionInvocationLogEntry[] = []
    const metrics: HogFunctionAppMetric[] = []

    let execResult: ExecResult | undefined
    const result: HogFunctionFilterResult = {
        match: false,
        logs,
        metrics,
    }

    if (!filters?.bytecode) {
        result.error = 'No filters bytecode'
        return result
    }

    try {
        execResult = execHog(filters.bytecode, {
            globals: filterGlobals,
            telemetry: enabledTelemetry,
        })

        if (execResult.error) {
            throw execResult.error
        }

        result.match = typeof execResult.result === 'boolean' && execResult.result

        if (!result.match) {
            metrics.push({
                team_id: hogFunction.team_id,
                app_source_id: hogFunction.id,
                metric_kind: 'other',
                metric_name: 'filtered',
                count: 1,
            })
        }
    } catch (error) {
        logger.error('🦔', `[HogFunction] Error filtering function`, {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            teamId: hogFunction.team_id,
            error: error.message,
            result: execResult,
        })

        metrics.push({
            team_id: hogFunction.team_id,
            app_source_id: hogFunction.id,
            metric_kind: 'other',
            metric_name: 'filtering_failed',
            count: 1,
        })

        if (eventUuid) {
            logs.push({
                team_id: hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: hogFunction.id,
                instance_id: new UUIDT().toString(),
                timestamp: DateTime.now(),
                level: 'error',
                message: `Error filtering event ${eventUuid}: ${error.message}`,
            })
        }
        result.error = error.message
    } finally {
        const duration = performance.now() - start

        // Re-using the constant from hog-executor.service.ts
        const DEFAULT_TIMEOUT_MS = 100

        hogFunctionFilterDuration.observe({ type: hogFunction.type }, duration)

        if (duration > DEFAULT_TIMEOUT_MS) {
            logger.error('🦔', `[HogFunction] Filter took longer than expected`, {
                hogFunctionId: hogFunction.id,
                hogFunctionName: hogFunction.name,
                teamId: hogFunction.team_id,
                duration,
                eventId: options?.eventUuid,
            })
        }
    }

    return result
}
