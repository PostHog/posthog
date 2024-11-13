import { kea, path } from 'kea'

import type { stackFrameLogicType } from './stackFrameLogicType'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),
    loaders(({ values }) => ({
        stackFrames: [
            [] as Record<string, Frame>,
            {
                loadFrames: async ({ frameIds }: { frameIds: string[] }) => {
                    const loadedFrameIds = values.stackFrames.map((f) => f.raw_id)
                    const ids = frameIds.filter((id) => loadedFrameIds.includes(id))
                    const response = await api.errorTracking.fetchStackFrames(ids)
                    return []
                },
            },
        ],
    })),
])
