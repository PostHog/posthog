import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext } from './types'

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),
    loaders(({ values }) => ({
        frameContexts: [
            {} as Record<string, ErrorTrackingStackFrameContext>,
            {
                loadFrameContexts: async ({ frames }: { frames: ErrorTrackingStackFrame[] }) => {
                    const loadedFrameIds = Object.keys(values.frameContexts)
                    const ids = frames
                        .filter(({ raw_id }) => !loadedFrameIds.includes(raw_id))
                        .map(({ raw_id }) => raw_id)
                    const response = await api.errorTracking.fetchStackFrames(ids)
                    return { ...values.frameContexts, ...response }
                },
            },
        ],
    })),
])
