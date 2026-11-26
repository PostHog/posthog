import { cheatCodeCampaignSlug } from 'lib/components/CheatCodes/cheatCodeCampaignSlug'
import { SceneExport } from 'scenes/sceneTypes'

import { CheatCodeRedemption } from './CheatCodeRedemption'
import { CouponRedemption } from './CouponRedemption'

export interface CouponsSceneProps {
    campaign?: string
}

export const scene: SceneExport<CouponsSceneProps> = {
    component: Coupons,
    paramsToProps: ({ params: { campaign } }) => ({
        campaign: campaign || undefined,
    }),
}

export function Coupons({ campaign }: CouponsSceneProps): JSX.Element {
    // People who heard about a cheat code try it as a campaign URL, such as /coupons/HESOYAM.
    const cheatCodeSlug = cheatCodeCampaignSlug(campaign || '')
    if (cheatCodeSlug) {
        return <CheatCodeRedemption campaignSlug={cheatCodeSlug} />
    }
    return <CouponRedemption campaign={campaign || ''} />
}

export default Coupons
