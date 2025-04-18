import './Billing.scss'

import { LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { billingLogic } from './billingLogic'
import { BillingOverview } from './BillingOverview'
import { BillingUsage } from './BillingUsage'
import { BillingUsage2 } from './BillingUsage2'
import { BillingUsage3 } from './BillingUsage3'
import { BillingUsage4 } from './BillingUsage4'
import { BillingUsage5 } from './BillingUsage5'

export const scene: SceneExport = {
    component: BillingSection,
    logic: billingLogic,
}

export function BillingSection(): JSX.Element {
    const { billingLoading } = useValues(billingLogic)
    const { location } = useValues(router)

    const section = location.pathname.includes('usage5')
        ? 'usage5'
        : location.pathname.includes('usage4')
        ? 'usage4'
        : location.pathname.includes('usage3')
        ? 'usage3'
        : location.pathname.includes('usage2')
        ? 'usage2'
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
                    { key: 'usage', label: 'Usage (LineGraph Insight)' },
                    { key: 'usage2', label: 'Usage (DataViz)' },
                    { key: 'usage3', label: 'Usage (LineGraph DataViz)' },
                    { key: 'usage4', label: 'Usage (Custom)' },
                    { key: 'usage5', label: 'Usage (Insight)' },
                ]}
            />

            {section === 'overview' && <BillingOverview />}
            {section === 'usage' && <BillingUsage />}
            {section === 'usage2' && <BillingUsage2 />}
            {section === 'usage3' && <BillingUsage3 />}
            {section === 'usage4' && <BillingUsage4 />}
            {section === 'usage5' && <BillingUsage5 />}
        </div>
    )
}
