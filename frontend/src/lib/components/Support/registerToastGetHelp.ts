import { router } from 'kea-router'

import { openSupportOptions, setGetHelpAction } from 'lib/lemon-ui/LemonToast/getHelp'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

/** Points the error toast's "Get help" button at in-app support instead of the docs fallback. */
export function registerToastGetHelp(): void {
    setGetHelpAction(() => {
        // In-app support here means the side panel, which is the surface that reads the billing plan:
        // it offers a ticket only to plans entitled to one. Self-hosted has no Support tab, and a scene
        // without a panel (onboarding, login) would fall through to the support modal, which asks for a
        // message from every plan. Both keep a link out to the support options docs.
        const isCloudOrDev = preflightLogic.findMounted()?.values.isCloudOrDev
        const sidePanelAvailable = sidePanelStateLogic.findMounted()?.values.sidePanelAvailable
        if (!isCloudOrDev || !sidePanelAvailable) {
            openSupportOptions()
            return
        }

        // `#panel=support` is the app's support entry point, which sidePanelStateLogic opens the panel
        // from. The panel handles the plan itself, so free plans land on PostHog AI and the community
        // forum rather than a ticket form.
        router.actions.push(router.values.location.pathname, router.values.searchParams, {
            ...router.values.hashParams,
            panel: SidePanelTab.Support,
        })
    })
}
