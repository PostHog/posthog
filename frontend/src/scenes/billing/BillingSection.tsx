import './Billing.scss'

import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Billing } from './Billing'
import { BillingSpendView } from './BillingSpendView'
import { BillingUsage } from './BillingUsage'
import { billingLogic } from './billingLogic'
import { BillingSectionId } from './types'

export const scene: SceneExport = {
    component: BillingSection,
    logic: billingLogic,
}

const tabs: { key: BillingSectionId; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'usage', label: 'Usage' },
    { key: 'spend', label: 'Spend' },
]

export function BillingSection(): JSX.Element {
    const { location, searchParams } = useValues(router)

    const section = location.pathname.includes('spend')
        ? 'spend'
        : location.pathname.includes('usage')
          ? 'usage'
          : 'overview'

    const handleTabChange = (key: BillingSectionId): void => {
        const newUrl = urls.organizationBillingSection(key)

        const currentHasParams = section === 'usage' || section === 'spend'
        const targetHasParams = key === 'usage' || key === 'spend'
        const shouldPreserveParams = currentHasParams && targetHasParams

        if (!shouldPreserveParams) {
            router.actions.push(newUrl)
            return
        }

        const paramsToPreserve = { ...searchParams }

        // When switching from spend to usage and breakdowns param is present,
        // ensure 'type' breakdown is included, since it's required for usage
        if (section === 'spend' && key === 'usage' && paramsToPreserve.breakdowns) {
            const currentBreakdowns = Array.isArray(paramsToPreserve.breakdowns) ? paramsToPreserve.breakdowns : []

            if (!currentBreakdowns.includes('type')) {
                paramsToPreserve.breakdowns = ['type', ...currentBreakdowns]
            }
        }

        router.actions.push(newUrl, paramsToPreserve)
    }

    return (
        <div className="flex flex-col">
            <LemonTabs activeKey={section} onChange={handleTabChange} tabs={tabs} />

            {section === 'overview' && <Billing />}
            {section === 'usage' && <BillingUsage />}
            {section === 'spend' && <BillingSpendView />}
        </div>
    )
}
