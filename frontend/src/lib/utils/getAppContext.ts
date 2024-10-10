import { AppContext, OrganizationType, PathType, TeamType } from '~/types'

declare global {
    export interface Window {
        POSTHOG_APP_CONTEXT?: AppContext
        SENTRY_DSN?: string
        SENTRY_ENVIRONMENT?: string
        STRIPE_PUBLIC_KEY?: string
    }
}

export function getAppContext(): AppContext | undefined {
    return window.POSTHOG_APP_CONTEXT || undefined
}

export function getDefaultEventName(): string {
    return getAppContext()?.default_event_name || PathType.PageView
}

export function getDefaultEventLabel(): string {
    const name = getDefaultEventName()
    return name === PathType.PageView ? 'Pageview' : name === PathType.Screen ? 'Screen' : name
}

// NOTE: Any changes to the teamId trigger a full page load so we don't use the logic
// This helps avoid circular imports
export function getCurrentTeamId(): TeamType['id'] {
    const maybeTeamId = getAppContext()?.current_team?.id
    if (!maybeTeamId) {
        throw new Error(`Project ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeTeamId
}

// NOTE: Any changes to the organizationId trigger a full page load so we don't use the logic
// This helps avoid circular imports
export function getCurrentOrganizationId(): OrganizationType['id'] {
    const maybeOrgId = getAppContext()?.current_team?.organization
    if (!maybeOrgId) {
        throw new Error(`Organization ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeOrgId
}
