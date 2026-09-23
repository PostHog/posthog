import { openSupportOptions } from 'lib/lemon-ui/LemonToast/getHelp'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

/**
 * Opens support where the person already is, for any "contact support" trigger.
 *
 * In-app support means the side panel, which is the surface that reads the billing plan: it offers a
 * ticket only to plans entitled to one. Self-hosted has no Support tab, and a scene without a panel
 * (onboarding, login) would fall through to the support modal, which asks for a message from every
 * plan. Those cases link out to the support options docs instead, tagged with `utmCampaign` so the
 * docs page still reports which surface sent the person.
 */
export function openInAppSupport(utmCampaign?: string): void {
    const isCloudOrDev = preflightLogic.findMounted()?.values.isCloudOrDev
    const sidePanelAvailable = sidePanelStateLogic.findMounted()?.values.sidePanelAvailable
    if (!isCloudOrDev || !sidePanelAvailable) {
        openSupportOptions(utmCampaign)
        return
    }

    // openSidePanel is the same action every other in-app support entry point calls. It writes the
    // `#panel=support` hash with `replace`, so Back leaves in one press instead of stranding an open
    // panel. The panel handles the plan itself, so free plans land on PostHog AI and the community
    // forum rather than a ticket form.
    sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)
}
