import './Billing.scss'
import './BillingUsage.scss'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { SceneExport } from 'scenes/sceneTypes'

import { billingLogic } from './billingLogic'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function Billing(): JSX.Element {
    return (
        <div className="BillingUsage flex">
            <div className="BillingUsage__sections">
                <ul className="space-y-px">
                    <li>
                        <LemonButton to="#" size="small" fullWidth>
                            Billing
                        </LemonButton>
                    </li>
                    <li>
                        <LemonButton to="#" size="small" fullWidth>
                            Usage
                        </LemonButton>
                    </li>
                </ul>
            </div>
            <div className="flex-1 w-full space-y-2 min-w-0">
                <LemonBanner type="info">Under construction</LemonBanner>
            </div>
        </div>
    )
}
