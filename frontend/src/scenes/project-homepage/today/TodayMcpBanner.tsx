import { useValues } from 'kea'

import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'
import { MCP_AD_LOGIC_PROPS } from 'lib/components/NavPanelAdvertisement/NavPanelMcpCard'

import { TodayMcpCallout } from './TodayMcpCallout'

export function TodayMcpBanner(): JSX.Element | null {
    const { hidden } = useValues(navPanelAdvertisementLogic(MCP_AD_LOGIC_PROPS))
    // Checked before the connection lookup mounts, so a dismissed banner never fetches connected apps.
    return hidden ? null : <TodayMcpCallout />
}
