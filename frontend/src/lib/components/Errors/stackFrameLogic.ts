import { actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord, ErrorTrackingSymbolSet } from './types'

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
                loadFromRawIds: async ({ rawIds }) => {
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
])
