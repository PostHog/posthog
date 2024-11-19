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

export type ContextLine = { number: number; line: string }
export type StackFrameContext = { before: ContextLine[]; line: ContextLine; after: ContextLine[] }

export const stackFrameLogic = kea<stackFrameLogicType>([
    path(['components', 'Errors', 'stackFrameLogic']),
    loaders(({ values }) => ({
        frameContexts: [
            {} as Record<string, string>,
            {
                loadFrameContexts: async ({ frames }: { frames: StackFrame[] }) => {
                    const loadedFrameIds = Object.keys(values.frameContexts)
                    const ids = frames
                        .filter(({ raw_id }) => loadedFrameIds.includes(raw_id))
                        .map(({ raw_id }) => raw_id)
                    const response = await api.errorTracking.fetchStackFrames(ids)
                    return { ...values.frameContexts, ...response }
                },
            },
        ],
    })),
])
