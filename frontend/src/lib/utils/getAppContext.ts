import { AppContext } from '~/types'

export function getAppContext(): AppContext | null {
    return (window as any)['POSTHOG_APP_CONTEXT'] || null
}
