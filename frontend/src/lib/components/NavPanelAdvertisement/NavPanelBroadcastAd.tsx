import { BindLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { captureBroadcastEvent } from './navPanelAdEvents'
import { AdvertisementCard, BroadcastPayload, NavPanelPlacement, broadcastDismissKey } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export function NavPanelBroadcastAd({
    broadcast,
    placement,
}: {
    broadcast: BroadcastPayload
    placement: NavPanelPlacement
}): JSX.Element | null {
    const logicProps = { dismissKey: broadcastDismissKey(broadcast) }
    const { hidden } = useValues(navPanelAdvertisementLogic(logicProps))
    const { broadcast: slug, productKey } = broadcast

    useEffect(() => {
        if (!hidden) {
            captureBroadcastEvent('shown', { broadcast: slug, productKey }, placement)
        }
    }, [slug, productKey, hidden, placement])

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
                onClose={() => captureBroadcastEvent('dismissed', broadcast, placement)}
            />
        </BindLogic>
    )
}
