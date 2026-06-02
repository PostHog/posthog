const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const teamPrefix = teamId ? `${teamId}__` : ''

export const aiObservabilityPreferenceStorage = {
    persist: true,
    prefix: `${teamPrefix}ai_observability`,
} as const
