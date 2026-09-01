import { router } from 'kea-router'

import { setGetHelpAction } from 'lib/lemon-ui/LemonToast/getHelp'

import type { SidePanelTab } from '~/types'

// `#panel=support` is the app's support entry point: sidePanelStateLogic opens the panel from it, and
// supportRouterLogic opens the modal instead on scenes that have no side panel. Written as a literal
// because `~/types` is too heavy to import for real at boot; the type still pins it to the enum.
const SUPPORT_PANEL_HASH: `${SidePanelTab.Support}` = 'support'

/** Points the error toast's "Get help" button at in-app support instead of the posthog.com fallback. */
export function registerToastGetHelp(): void {
    setGetHelpAction(() => {
        router.actions.push(router.values.location.pathname, router.values.searchParams, {
            ...router.values.hashParams,
            panel: SUPPORT_PANEL_HASH,
        })
    })
}
