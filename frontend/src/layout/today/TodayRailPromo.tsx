import { NAV_PANEL_PLACEMENT, type NavPanelSlot } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'

import { TodayRailPromoTile } from './TodayRailPromoTile'

const RAIL_SLOT: NavPanelSlot = {
    placement: NAV_PANEL_PLACEMENT.RAIL,
    frame: (card, teaser) => <TodayRailPromoTile card={card} teaser={teaser} />,
}

export function TodayRailPromo(): JSX.Element | null {
    return <NavPanelAdvertisement slot={RAIL_SLOT} />
}
