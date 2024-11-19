import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'

export interface ErrorTrackingStackFrame {
    filename: string
    lineno: number
    colno: number
    function: string
    in_app?: boolean
    raw_id: string
    created_at: string
    resolved: boolean
    context: string | null
    contents: Record<string, any> // More flexible for varying content structures
}

export interface ErrorTrackingSymbolSet {
    id: string
    ref: string
    team_id: number
    created_at: string
    storage_ptr: string | null
    failure_reason: string | null
}

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
