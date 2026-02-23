import { actions, kea, listeners, path, reducers } from 'kea'
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
        setLoadStartTime: (startTime: number | null) => ({ startTime }),
    }),

    reducers({
        loadStartTime: [
            null as number | null,
            {
                setLoadStartTime: (_, { startTime }) => startTime,
            },
        ],
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

    listeners(({ actions, values }) => ({
        loadFromRawIds: () => {
            actions.setLoadStartTime(performance.now())
        },
        loadFromRawIdsSuccess: ({ stackFrameRecords }) => {
            const durationMs =
                values.loadStartTime !== null ? Math.round(performance.now() - values.loadStartTime) : null
            actions.setLoadStartTime(null)

            const recordsWithContext = Object.values(stackFrameRecords).filter((record) => record.context)
            posthog.capture('error_tracking_stack_trace_loaded', {
                duration_ms: durationMs,
                frame_count: recordsWithContext.length,
            })
        },
        loadFromRawIdsFailure: () => {
            actions.setLoadStartTime(null)
        },
    })),
])
