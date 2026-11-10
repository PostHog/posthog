import { useValues } from 'kea'

import { NavPanelSlot, SIDEBAR_SLOT } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'
import { MCP_AD_LOGIC_PROPS, NavPanelMcpCard } from './NavPanelMcpCard'

/** Asks users whose agent has not connected to connect the PostHog MCP server. */
export function NavPanelMcpAd({ slot = SIDEBAR_SLOT }: { slot?: NavPanelSlot }): JSX.Element | null {
    const { hidden } = useValues(navPanelAdvertisementLogic(MCP_AD_LOGIC_PROPS))
    // Checked before the connection lookup mounts, so a dismissed card never fetches connected apps.
    return hidden ? null : <NavPanelMcpCard slot={slot} />
}
