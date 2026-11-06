import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { BroadcastPayload, AdvertisementCard, NAV_PANEL_CARD_TYPE } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export function NavPanelBroadcastAd({ broadcast }: { broadcast: BroadcastPayload }): JSX.Element | null {
    const logicProps = { dismissKey: `broadcast-${broadcast.broadcast}` }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)

    useEffect(() => {
        if (!hidden) {
            posthog.capture('nav panel broadcast shown', {
                broadcast: broadcast.broadcast,
                card_type: NAV_PANEL_CARD_TYPE.BROADCAST,
                product_key: broadcast.productKey,
            })
        }
    }, [broadcast.broadcast, broadcast.productKey, hidden])

    if (hidden) {
        return null
    }

    return (
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
                    })
                }}
            />
        </BindLogic>
    )
}
