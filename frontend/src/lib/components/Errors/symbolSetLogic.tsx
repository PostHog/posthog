import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { symbolSetLogicType } from './symbolSetLogicType'
import { ErrorTrackingStackFrameRecord, ErrorTrackingSymbolSet } from './types'

export const symbolSetLogic = kea<symbolSetLogicType>([
    path(['components', 'Errors', 'symbolSetLogic']),
    loaders(({ values }) => ({
        symbolSets: [
            [] as ErrorTrackingSymbolSet[],
            {
                loadSymbolSets: async () => {
                    return await api.errorTracking.fetchSymbolSets()
                },
            },
        ],
        symbolSetStackFrames: [
            {} as Record<string, ErrorTrackingStackFrameRecord[]>,
            {
                loadStackFrames: async ({ symbolSetId }: { symbolSetId: string }) => {
                    const frames = await api.errorTracking.fetchSymbolSetStackFrames(symbolSetId)
                    return {
                        ...values.symbolSetStackFrames,
                        [symbolSetId]: frames,
                    }
                },
            },
        ],
    })),
])
