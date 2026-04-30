import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'

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
                const query = hogql`
SELECT properties
FROM events
WHERE $session_id = ${props.sessionId}
ORDER BY timestamp DESC
LIMIT 1`
                const result = await api.queryHogQL(query, {
                    scene: 'ReplayCaptureDiagnostics',
                    productKey: 'session_replay',
                })

                breakpoint()

                const row = result?.results?.[0]?.[0]
                if (!row) {
                    return null
                }
                return typeof row === 'string' ? JSON.parse(row) : row
            },
        },
    })),
])
