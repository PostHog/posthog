import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

interface AIObservabilityPreferenceStorageConfig {
    persist: true
    storageKey: string
}

export function buildAiObservabilityStorageConfig(storageKey: string): AIObservabilityPreferenceStorageConfig {
    const teamId = getCurrentTeamIdOrNone()
    const teamPrefix = teamId ? `${teamId}__` : ''

    return {
        persist: true,
        storageKey: `${teamPrefix}ai_observability.${storageKey}`,
    }
}
