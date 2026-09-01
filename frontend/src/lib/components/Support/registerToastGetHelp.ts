import { router } from 'kea-router'

import { openSupportPage, setGetHelpAction } from 'lib/lemon-ui/LemonToast/getHelp'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { SidePanelTab } from '~/types'

/** Points the error toast's "Get help" button at in-app support instead of the posthog.com fallback. */
export function registerToastGetHelp(): void {
    setGetHelpAction(() => {
        // Self-hosted instances have no support panel to open, so they keep the posthog.com page.
        // Mirrors the gate the side panel puts its Support tab behind.
        const isCloudOrDev =
            preflightLogic.findMounted()?.values.preflight?.cloud || process.env.NODE_ENV === 'development'
        if (!isCloudOrDev) {
            openSupportPage()
            return
        }

        // `#panel=support` is the app's support entry point: sidePanelStateLogic opens the panel from it,
        // and supportRouterLogic opens the modal on scenes that have no panel. The panel handles the plan
        // itself, so free plans land on PostHog AI and the community forum rather than a ticket form.
        router.actions.push(router.values.location.pathname, router.values.searchParams, {
            ...router.values.hashParams,
            panel: SidePanelTab.Support,
        })
    })
}
