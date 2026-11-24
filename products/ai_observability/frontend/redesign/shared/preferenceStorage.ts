import { buildTeamScopedStorageConfig } from 'lib/logic/persistence'

export const buildAiObservabilityStorageConfig = (
    storageKey: string
): ReturnType<typeof buildTeamScopedStorageConfig> => buildTeamScopedStorageConfig(`ai_observability.${storageKey}`)
