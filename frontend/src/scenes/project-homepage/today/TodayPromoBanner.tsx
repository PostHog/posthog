import { useValues } from 'kea'

import { NAV_PANEL_CARD_TYPE } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'

import { TodayBroadcastBanner } from './TodayBroadcastBanner'
import { todayLogic } from './todayLogic'
import { TodayMcpBanner } from './TodayMcpBanner'

export function TodayPromoBanner(): JSX.Element | null {
    const { promoBanner } = useValues(todayLogic)

    switch (promoBanner?.type) {
        case NAV_PANEL_CARD_TYPE.BROADCAST:
            return <TodayBroadcastBanner broadcast={promoBanner.broadcast} />
        case NAV_PANEL_CARD_TYPE.MCP_CONNECT:
            return <TodayMcpBanner />
        default:
            return null
    }
}
