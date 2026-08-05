import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { CampaignPayload, AdvertisementCard } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export function NavPanelCampaignAd({ campaign }: { campaign: CampaignPayload }): JSX.Element | null {
    const logicProps = { campaign: `campaign-${campaign.campaign}` }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)

    useEffect(() => {
        if (!hidden) {
            posthog.capture('nav panel campaign shown', { campaign: campaign.campaign })
        }
    }, [campaign.campaign, hidden])

    if (hidden) {
        return null
    }

    return (
        <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
            <AdvertisementCard
                emoji={campaign.emoji}
                emojiLabel={campaign.emojiLabel}
                title={campaign.title}
                text={campaign.text}
                onClose={() => {
                    posthog.capture('nav panel campaign dismissed', {
                        campaign: campaign.campaign,
                    })
                }}
            />
        </BindLogic>
    )
}
