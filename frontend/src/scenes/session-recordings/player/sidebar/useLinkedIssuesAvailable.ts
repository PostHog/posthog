import { useValues } from 'kea'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function useLinkedIssuesAvailable(): boolean {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    return (
        getIntegrationsByKind(['linear', 'github', 'gitlab', 'jira']).length > 0 ||
        (sessionPlayerMetaData?.external_references ?? []).length > 0
    )
}
