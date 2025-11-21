import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { CouponRedemption } from './CouponRedemption'
import { campaignConfigs } from './campaigns'

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
    if (!campaign) {
        return <NotFound object="coupon campaign" />
    }

    const config = campaignConfigs[campaign]

    if (!config) {
        return (
            <NotFound
                object="coupon campaign"
                caption={
                    <>
                        The campaign "{campaign}" does not exist or is not available.
                        <br />
                        Please check the URL and try again.
                    </>
                }
            />
        )
    }

    return <CouponRedemption campaign={campaign} config={config} />
}

export default Coupons
