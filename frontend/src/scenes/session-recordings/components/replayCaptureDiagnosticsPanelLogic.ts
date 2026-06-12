import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import type { replayCaptureDiagnosticsPanelLogicType } from './replayCaptureDiagnosticsPanelLogicType'

export interface ReplayCaptureDiagnosticsPanelLogicProps {
    sessionId: string
}

export const replayCaptureDiagnosticsPanelLogic = kea<replayCaptureDiagnosticsPanelLogicType>([
    path(['scenes', 'session-recordings', 'components', 'replayCaptureDiagnosticsPanelLogic']),
    props({} as ReplayCaptureDiagnosticsPanelLogicProps),
    key((props) => props.sessionId),
    defaults({
        sessionEventProperties: null as Record<string, any> | null,
    }),
    lazyLoaders(({ props }) => ({
        sessionEventProperties: {
            loadSessionEventProperties: async (_, breakpoint): Promise<Record<string, any> | null> => {
                const result = await api.recordings.getCaptureDiagnostics(props.sessionId)
                breakpoint()
                return result.properties ?? null
            },
        },
    })),
])
