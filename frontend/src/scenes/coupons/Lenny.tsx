import { SceneExport } from 'scenes/sceneTypes'

import { CouponRedemption } from './CouponRedemption'
import { lennyCampaign } from './campaigns/lenny'

export const scene: SceneExport = {
    component: LennyCoupon,
}

export function LennyCoupon(): JSX.Element {
    return <CouponRedemption campaign="lenny" config={lennyCampaign} />
}

export default LennyCoupon
