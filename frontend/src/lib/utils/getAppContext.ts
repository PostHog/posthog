import { getOAuthContextIds, isOAuthMode } from 'lib/oauth/oauthClient'

import { AppContext, OrganizationType, PathType, TeamType, UserType } from '~/types'

declare global {
    export interface Window {
        POSTHOG_APP_CONTEXT?: AppContext
        STRIPE_PUBLIC_KEY?: string
    }
}

export function getAppContext(): AppContext | undefined {
    // When logged into a remote cloud region over OAuth, ignore the local backend's
    // server-rendered context so the whole app bootstraps from the remote region instead.
    if (isOAuthMode()) {
        return undefined
    }
    return window.POSTHOG_APP_CONTEXT || undefined
}

export function getProjectEventExistence(): { hasPageview: boolean; hasScreen: boolean } {
    const ctx = getAppContext()
    return {
        hasPageview: ctx?.has_pageview ?? true,
        hasScreen: ctx?.has_screen ?? true,
    }
}

export function getDefaultEventName(): string | null {
    const context = getAppContext()
    // If context exists but default_event_name is explicitly null, return null (all events)
    // If context doesn't exist, fall back to $pageview for backwards compatibility
    if (context === undefined) {
        return PathType.PageView
    }
    return context.default_event_name ?? null
}

export function getDefaultEventLabel(): string {
    const name = getDefaultEventName()
    if (name === null) {
        return 'All events'
    }
    return name === PathType.PageView ? 'Pageview' : name === PathType.Screen ? 'Screen' : name
}

// NOTE: Any changes to the teamId trigger a full page load so we don't use the logic
// This helps avoid circular imports
export function getCurrentTeamId(): TeamType['id'] {
    const maybeTeamId = getAppContext()?.current_team?.id ?? (isOAuthMode() ? getOAuthContextIds()?.teamId : undefined)
    if (!maybeTeamId) {
        throw new Error(`Project ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeTeamId
}

export function getCurrentTeamIdOrNone(): TeamType['id'] | null {
    return getAppContext()?.current_team?.id ?? (isOAuthMode() ? (getOAuthContextIds()?.teamId ?? null) : null)
}

// NOTE: Any changes to the userId trigger a full page load so we don't use the logic
// This helps avoid circular imports
export function getCurrentUserId(): UserType['uuid'] {
    const maybeUserId =
        getAppContext()?.current_user?.uuid ?? (isOAuthMode() ? getOAuthContextIds()?.userId : undefined)
    if (!maybeUserId) {
        throw new Error(`User ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeUserId
}

export function getCurrentUserIdOrNone(): UserType['uuid'] | null {
    return getAppContext()?.current_user?.uuid ?? (isOAuthMode() ? (getOAuthContextIds()?.userId ?? null) : null)
}

// NOTE: Any changes to the organizationId trigger a full page load so we don't use the logic
// This helps avoid circular imports
export function getCurrentOrganizationId(): OrganizationType['id'] {
    const maybeOrgId =
        getAppContext()?.current_team?.organization ??
        (isOAuthMode() ? getOAuthContextIds()?.organizationId : undefined)
    if (!maybeOrgId) {
        throw new Error(`Organization ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeOrgId
}

export const isUserLoggedIn = (): boolean => !getAppContext()?.anonymous
