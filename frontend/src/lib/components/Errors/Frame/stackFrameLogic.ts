import { actions, afterMount, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord, ErrorTrackingSymbolSet } from '../types'
import type { stackFrameLogicType } from './stackFrameLogicType'

export type KeyedStackFrameRecords = Record<ErrorTrackingStackFrameRecord['raw_id'], ErrorTrackingStackFrameRecord>

function mapStackFrameRecords(
    newRecords: ErrorTrackingStackFrameRecord[],
    initialRecords: KeyedStackFrameRecords
): KeyedStackFrameRecords {
    return newRecords.reduce(
        (frames, record) => {
            frames[record.raw_id] = record
            return frames
        },
        { ...initialRecords }
    )
}

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),

    actions({
        loadFromRawIds: (rawIds: ErrorTrackingStackFrame['raw_id'][]) => ({ rawIds }),
        loadForSymbolSet: (symbolSetId: ErrorTrackingSymbolSet['id']) => ({ symbolSetId }),
    }),

    loaders(({ values }) => ({
        stackFrameRecords: [
            {} as KeyedStackFrameRecords,
            {
                loadFromRawIds: async ({ rawIds }: { rawIds: ErrorTrackingStackFrame['raw_id'][] }) => {
                    const loadedRawIds = Object.keys(values.stackFrameRecords)
                    rawIds = rawIds.filter((rawId) => !loadedRawIds.includes(rawId))
                    if (rawIds.length === 0) {
                        return values.stackFrameRecords
                    }
                    const { results } = await api.errorTracking.stackFrames(rawIds)

                    return mapStackFrameRecords(results, values.stackFrameRecords)
                },
                loadForSymbolSet: async ({ symbolSetId }) => {
                    const { results } = await api.errorTracking.symbolSetStackFrames(symbolSetId)
                    return mapStackFrameRecords(results, values.stackFrameRecords)
                },
            },
        ],
    })),

    listeners(({ cache }) => ({
        loadFromRawIds: () => {
            const loadStartedAt = performance.now()
            cache.currentLoadStartedAt = loadStartedAt
            cache.currentLoadType = cache.hasLoadedStackFrames ? 'subsequent' : 'initial'
        },
        loadFromRawIdsSuccess: ({ stackFrameRecords }) => {
            const loadType = cache.currentLoadType ?? 'initial'
            const loadStartedAt = cache.currentLoadStartedAt
            const requestDurationMs =
                loadStartedAt !== null && loadStartedAt !== undefined
                    ? Math.round(performance.now() - loadStartedAt)
                    : null
            const mountDurationMs =
                loadType === 'initial' && cache.mountedAt ? Math.round(performance.now() - cache.mountedAt) : null
            cache.currentLoadStartedAt = null
            cache.currentLoadType = null

            const recordsWithContext = Object.values(stackFrameRecords).filter((record) => record.context)
            if (recordsWithContext.length > 0) {
                cache.hasLoadedStackFrames = true
            }

            posthog.capture('error_tracking_stack_trace_loaded', {
                load_type: loadType,
                duration_ms: requestDurationMs,
                duration_since_mount_ms: mountDurationMs,
                frame_count: recordsWithContext.length,
            })
        },
        loadFromRawIdsFailure: () => {
            cache.currentLoadStartedAt = null
            cache.currentLoadType = null
        },
    })),
    afterMount(({ cache }) => {
        cache.mountedAt = performance.now()
        cache.hasLoadedStackFrames = false
        cache.currentLoadStartedAt = null as number | null
        cache.currentLoadType = null as 'initial' | 'subsequent' | null
    }),
])
