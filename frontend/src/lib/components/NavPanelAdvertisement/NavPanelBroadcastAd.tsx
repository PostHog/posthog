import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import {
    BroadcastPayload,
    AdvertisementCard,
    NAV_PANEL_CARD_TYPE,
    NavPanelSlot,
    SIDEBAR_SLOT,
} from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export function NavPanelBroadcastAd({
    broadcast,
    slot = SIDEBAR_SLOT,
}: {
    broadcast: BroadcastPayload
    slot?: NavPanelSlot
}): JSX.Element | null {
    const logicProps = { dismissKey: `broadcast-${broadcast.broadcast}` }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)

    useEffect(() => {
        if (!hidden) {
            posthog.capture('nav panel broadcast shown', {
                broadcast: broadcast.broadcast,
                card_type: NAV_PANEL_CARD_TYPE.BROADCAST,
                product_key: broadcast.productKey,
                placement: slot.placement,
            })
        }
    }, [broadcast.broadcast, broadcast.productKey, hidden, slot.placement])

    if (hidden) {
        return null
    }

    return slot.frame(
        <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
            <AdvertisementCard
                emoji={broadcast.emoji}
                emojiLabel={broadcast.emojiLabel}
                title={broadcast.title}
                text={broadcast.text}
                onClose={() => {
                    posthog.capture('nav panel broadcast dismissed', {
                        broadcast: broadcast.broadcast,
                        card_type: NAV_PANEL_CARD_TYPE.BROADCAST,
                        product_key: broadcast.productKey,
                        placement: slot.placement,
                    })
                }}
            />
        </BindLogic>,
        { id: logicProps.dismissKey, cardType: NAV_PANEL_CARD_TYPE.BROADCAST, title: broadcast.title }
    )
}
