import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'

export interface StackFrame {
    filename: string
    lineno: number
    colno: number
    function: string
    in_app?: boolean
}

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),
    loaders(({ values }) => ({
        stackFrames: [
            {} as Record<string, StackFrame>,
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
