import './Billing.scss'

import { LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { billingLogic } from './billingLogic'
import { BillingOverview } from './BillingOverview'
import { BillingSpendView } from './BillingSpendView'
import { BillingUsage } from './BillingUsage'

export const scene: SceneExport = {
    component: BillingSection,
    logic: billingLogic,
}

export function BillingSection(): JSX.Element {
    const { billingLoading } = useValues(billingLogic)
    const { location } = useValues(router)

    const section = location.pathname.includes('spend')
        ? 'spend'
        : location.pathname.includes('usage')
        ? 'usage'
        : 'overview'

    useEffect(() => {
        if (!billingLoading && location.pathname === '/organization/billing') {
            router.actions.push(urls.organizationBillingSection('overview'))
        }
    }, [billingLoading, location.pathname])

    return (
        <div className="flex flex-col">
            <LemonTabs
                activeKey={section}
                onChange={(key) => router.actions.push(urls.organizationBillingSection(key))}
                tabs={[
                    { key: 'overview', label: 'Overview' },
                    { key: 'spend', label: 'Spend' },
                    { key: 'usage', label: 'Usage' },
                ]}
            />

            {section === 'overview' && <BillingOverview />}
            {section === 'usage' && <BillingUsage />}
            {section === 'spend' && <BillingSpendView />}
        </div>
    )
}
