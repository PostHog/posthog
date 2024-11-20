import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'
import { ErrorTrackingStackFrame } from './types'

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),
    loaders(({ values }) => ({
        stackFrames: [
            {} as Record<string, ErrorTrackingStackFrame>,
            {
                loadFrames: async ({ frameIds }: { frameIds: string[] }) => {
                    const loadedFrameIds = Object.keys(values.stackFrames)
                    const ids = frameIds.filter((id) => loadedFrameIds.includes(id))
                    await api.errorTracking.fetchStackFrames(ids)
                    return {}
                },
            },
        ],
    })),
])
