import { AppContext, PathType } from '~/types'

export function getAppContext(): AppContext | undefined {
    return (window as any)['POSTHOG_APP_CONTEXT'] || undefined
}

export function getDefaultEventName(): string {
    return getAppContext()?.default_event_name || PathType.PageView
}
