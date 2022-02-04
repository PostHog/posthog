import { AppContext, PathType, Realm } from '~/types'

declare global {
    export interface Window {
        POSTHOG_APP_CONTEXT?: AppContext
    }
}

export function getAppContext(): AppContext | undefined {
    return window.POSTHOG_APP_CONTEXT || undefined
}

export function getDefaultEventName(): string {
    return getAppContext()?.default_event_name || PathType.PageView
}

export function getUpgradeLink(): string {
    return getAppContext()?.preflight.realm == Realm.Cloud ? '/organization/billing' : 'https://posthog.com/pricing'
}
