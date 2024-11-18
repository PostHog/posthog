import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { stackFrameLogicType } from './stackFrameLogicType'

export interface StackFrame {
    raw_id: string
    filename: string
    lineno: number
    colno: number
    function: string
    in_app?: boolean
}

export type StackFrameContext = { pre_context: string[]; line_context: string; post_context: string[] }

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),
    loaders(({ values }) => ({
        stackFrameContexts: [
            {} as Record<string, StackFrameContext>,
            {
                loadFrameContexts: async ({ frameIds }: { frameIds: string[] }) => {
                    const loadedFrameIds = Object.keys(values.stackFrameContexts)
                    const ids = frameIds.filter((id) => loadedFrameIds.includes(id))
                    const response = await api.errorTracking.fetchStackFrames(ids)
                    const newValues = { ...values.stackFrameContexts }
                    response.forEach(({ raw_id, context }) => {
                        newValues[raw_id] = context
                    })
                    return newValues
                },
            },
        ],
    })),
])
