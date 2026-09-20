import posthog from 'posthog-js'
import { useEffect } from 'react'

import { AccountsEvents } from './constants'

export type AccountPanel = 'pinned_properties' | 'notes' | 'related_users'

/**
 * Counts the people a failed load actually blocks. The client request-failure events count dropped
 * requests, which is a different number: most of them recover on retry and reach nobody.
 */
export function usePanelLoadBlocked(panel: AccountPanel, isBlocked: boolean): void {
    useEffect(() => {
        if (isBlocked) {
            posthog.capture(AccountsEvents.PanelLoadBlocked, { panel })
        }
    }, [panel, isBlocked])
}
