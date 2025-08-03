import { exponentialBuckets, Histogram } from 'prom-client'

import { SessionRecordingV2MetadataSwitchoverDate } from '~/types'

import { timeoutGuard } from '../utils/db/utils'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'

interface FunctionInstrumentation<T> {
    statsKey: string
    func: () => Promise<T>
    timeout?: number
    timeoutMessage?: string
    timeoutContext?: () => Record<string, any>
    teamId?: number
    logExecutionTime?: boolean
    sendException?: boolean
}

const logTime = (startTime: number, statsKey: string, error?: any) => {
    logger.info('⏱️', `${statsKey} took ${Math.round(performance.now() - startTime)}ms`, {
        error,
        statsKey,
        type: 'instrumented_function_time_log',
    })
}

export async function runInstrumentedFunction<T>({
    timeoutMessage,
    timeout,
    timeoutContext,
    func,
    statsKey,
    teamId,
    logExecutionTime = false,
    sendException = true,
}: FunctionInstrumentation<T>): Promise<T> {
    const t = timeoutGuard(
        timeoutMessage ?? `Timeout warning for '${statsKey}'!`,
        timeoutContext,
        timeout,
        sendException
    )
    const startTime = performance.now()
    const end = instrumentedFunctionDuration.startTimer({
        function: statsKey,
    })

    try {
        const result = await func()
        end({ success: 'true' })
        if (logExecutionTime) {
            logTime(startTime, statsKey)
        }
        return result
    } catch (error) {
        end({ success: 'false' })
        logger.info('🔔', error)
        if (logExecutionTime) {
            logTime(startTime, statsKey, error)
        }
        captureException(error, { tags: { team_id: teamId } })
        throw error
    } finally {
        clearTimeout(t)
    }
}

const instrumentedFunctionDuration = new Histogram({
    name: 'instrumented_function_duration_seconds',
    help: 'Processing time and success status of internal functions',
    labelNames: ['function', 'success'],
    // We need to cover a pretty wide range, so buckets are set pretty coarse for now
    // and cover 25ms -> 102seconds. We can revisit them later on.
    buckets: exponentialBuckets(0.025, 4, 7),
})

export const eventPassesMetadataSwitchoverTest = (
    timestamp: number,
    metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate
): boolean => {
    if (metadataSwitchoverDate === null) {
        return false
    }

    if (metadataSwitchoverDate === true) {
        return true
    }

    return timestamp >= metadataSwitchoverDate.getTime()
}

export const parseSessionRecordingV2MetadataSwitchoverDate = (
    config: string
): SessionRecordingV2MetadataSwitchoverDate => {
    let metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate = null
    if (config === '*') {
        metadataSwitchoverDate = true
        logger.info('SESSION_RECORDING_V2_METADATA_SWITCHOVER asterisk enabled', {
            value: config,
        })
    } else if (config) {
        const parsed = Date.parse(config)
        if (!isNaN(parsed)) {
            metadataSwitchoverDate = new Date(parsed)
            logger.info('SESSION_RECORDING_V2_METADATA_SWITCHOVER enabled', {
                value: config,
                parsedDate: metadataSwitchoverDate.toISOString(),
            })
        } else {
            throw new Error('SESSION_RECORDING_V2_METADATA_SWITCHOVER is not a valid ISO datetime or "*": ' + config)
        }
    }
    return metadataSwitchoverDate
}
