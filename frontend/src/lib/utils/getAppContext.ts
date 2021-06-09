import { AppContext } from '~/types'

export function getAppContext(): AppContext | undefined {
    return (window as any)['POSTHOG_APP_CONTEXT'] || undefined
}
