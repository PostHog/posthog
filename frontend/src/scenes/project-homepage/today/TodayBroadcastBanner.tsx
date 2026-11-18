import { useValues } from 'kea'
import { useEffect } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { captureBroadcastEvent } from 'lib/components/NavPanelAdvertisement/navPanelAdEvents'
import {
    BroadcastPayload,
    NAV_PANEL_PLACEMENT,
    broadcastDismissKey,
} from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { navPanelAdvertisementLogic } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisementLogic'

import { TodayPromoDismissButton } from './TodayPromoDismissButton'

export function TodayBroadcastBanner({ broadcast }: { broadcast: BroadcastPayload }): JSX.Element | null {
    const dismissKey = broadcastDismissKey(broadcast)
    const { hidden } = useValues(navPanelAdvertisementLogic({ dismissKey }))
    const { broadcast: slug, productKey } = broadcast

    useEffect(() => {
        if (!hidden) {
            captureBroadcastEvent('shown', { broadcast: slug, productKey }, NAV_PANEL_PLACEMENT.TODAY_HOME)
        }
    }, [slug, productKey, hidden])

    if (hidden) {
        return null
    }

    return (
        <Item variant="outline" className="mb-8" data-attr="today-broadcast-banner">
            <ItemMedia variant="icon">
                <span role="img" aria-label={broadcast.emojiLabel}>
                    {broadcast.emoji}
                </span>
            </ItemMedia>
            <ItemContent>
                <ItemTitle>{broadcast.title}</ItemTitle>
                <ItemDescription className="line-clamp-none">{broadcast.text}</ItemDescription>
            </ItemContent>
            <ItemActions>
                <TodayPromoDismissButton
                    dismissKey={dismissKey}
                    onDismiss={() => captureBroadcastEvent('dismissed', broadcast, NAV_PANEL_PLACEMENT.TODAY_HOME)}
                    dataAttr="today-broadcast-banner-dismiss"
                />
            </ItemActions>
        </Item>
    )
}
