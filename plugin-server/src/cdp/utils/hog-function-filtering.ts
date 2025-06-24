import { ExecResult } from '@posthog/hogvm'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { HogFlow } from '../../schema/hogflow'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import { execHog } from '../services/hog-executor.service'
import { HogFunctionFilterGlobals, HogFunctionType, LogEntry, MinimalAppMetric } from '../types'

const hogFunctionFilterDuration = new Histogram({
    name: 'cdp_hog_function_filter_duration_ms',
    help: 'Processing time for filtering a function',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
    labelNames: ['type'],
})

interface HogFilterResult {
    match: boolean
    error?: unknown
    logs: LogEntry[]
    metrics: MinimalAppMetric[]
}

/**
 * Shared utility to check if an event matches the filters of a HogFunction.
 * Used by both the HogExecutorService (for destinations) and HogTransformerService (for transformations).
 */
export function filterFunctionInstrumented(options: {
    fn: HogFunctionType | HogFlow
    filterGlobals: HogFunctionFilterGlobals
    /** Optional filters to use instead of those on the function */
    filters: HogFunctionType['filters']
    /** Whether to enable telemetry for this function at the hogvm level */
    enabledTelemetry?: boolean
    /** The event UUID to use for logging */
    eventUuid?: string
}): HogFilterResult {
    const { fn, filters, filterGlobals, enabledTelemetry, eventUuid } = options
    const type = 'type' in fn ? fn.type : 'hogflow'
    const fnKind = 'type' in fn ? 'HogFunction' : 'HogFlow'
    const start = performance.now()
    const logs: LogEntry[] = []
    const metrics: MinimalAppMetric[] = []

    let execResult: ExecResult | undefined
    const result: HogFilterResult = {
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
                team_id: fn.team_id,
                app_source_id: fn.id,
                metric_kind: 'other',
                metric_name: 'filtered',
                count: 1,
            })
        }
    } catch (error) {
        logger.error('🦔', `[${fnKind}] Error filtering function`, {
            functionId: fn.id,
            functionName: fn.name,
            teamId: fn.team_id,
            error: error.message,
            result: execResult,
        })

        metrics.push({
            team_id: fn.team_id,
            app_source_id: fn.id,
            metric_kind: 'other',
            metric_name: 'filtering_failed',
            count: 1,
        })

        if (eventUuid) {
            logs.push({
                team_id: fn.team_id,
                log_source: fnKind === 'HogFunction' ? 'hog_function' : 'hog_flow',
                log_source_id: fn.id,
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

        hogFunctionFilterDuration.observe({ type }, duration)

        if (duration > DEFAULT_TIMEOUT_MS) {
            logger.error('🦔', `[${fnKind}] Filter took longer than expected`, {
                functionId: fn.id,
                functionName: fn.name,
                teamId: fn.team_id,
                duration,
                eventId: options?.eventUuid,
            })
        }
    }

    return result
}
