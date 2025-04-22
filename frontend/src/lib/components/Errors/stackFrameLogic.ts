import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord, ErrorTrackingSymbolSet } from './types'

export type KeyedStackFrameRecords = Record<ErrorTrackingStackFrameRecord['raw_id'], ErrorTrackingStackFrameRecord>

function mapStackFrameRecords(
    newRecords: ErrorTrackingStackFrameRecord[],
    initialRecords: KeyedStackFrameRecords
): KeyedStackFrameRecords {
    return newRecords.reduce((frames, record) => ({ ...frames, [record.raw_id]: record }), initialRecords)
}

interface FingerprintFrame {
    type: 'frame'
    raw_id: string
    pieces: string[]
}

interface FingerprintException {
    type: 'exception'
    id: string // Exception ID
    pieces: string[]
}

interface FingerprintManual {
    type: 'manual'
}

export type FingerprintRecordPart = FingerprintManual | FingerprintFrame | FingerprintException

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),

    actions({
        loadFromRawIds: (rawIds: ErrorTrackingStackFrame['raw_id'][]) => ({ rawIds }),
        loadForSymbolSet: (symbolSetId: ErrorTrackingSymbolSet['id']) => ({ symbolSetId }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
        setFrameOrderReversed: (reverseOrder: boolean) => ({ reverseOrder }),
    }),

    reducers(() => ({
        showAllFrames: [
            false,
            { persist: true },
            {
                setShowAllFrames: (_, { showAllFrames }) => showAllFrames,
            },
        ],
        frameOrderReversed: [
            false,
            { persist: true },
            {
                setFrameOrderReversed: (_, { reverseOrder }) => reverseOrder,
            },
        ],
    })),

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
