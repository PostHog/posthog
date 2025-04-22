import './Billing.scss'

import { LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Billing } from './Billing'
import { billingLogic } from './billingLogic'
import { BillingSpendView } from './BillingSpendView'
import { BillingUsage } from './BillingUsage'

export const scene: SceneExport = {
    component: BillingSection,
    logic: billingLogic,
}

export function BillingSection(): JSX.Element {
    const { location } = useValues(router)

    const section = location.pathname.includes('spend')
        ? 'spend'
        : location.pathname.includes('usage')
        ? 'usage'
        : 'overview'

    return (
        <div className="flex flex-col">
            <LemonTabs
                activeKey={section}
                onChange={(key) => router.actions.push(urls.organizationBillingSection(key))}
                tabs={[
                    { key: 'overview', label: 'Overview' },
                    { key: 'usage', label: 'Usage' },
                    { key: 'spend', label: 'Spend' },
                ]}
            />

            {section === 'overview' && <Billing />}
            {section === 'usage' && <BillingUsage />}
            {section === 'spend' && <BillingSpendView />}
        </div>
    )
}
