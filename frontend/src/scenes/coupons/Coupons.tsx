import { SceneExport } from 'scenes/sceneTypes'

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
    return <CouponRedemption campaign={campaign || ''} />
}

export default Coupons
