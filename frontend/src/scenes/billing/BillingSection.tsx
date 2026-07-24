import './Billing.scss'

import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Billing } from './Billing'
import { billingLogic } from './billingLogic'
import { BillingSpendView } from './BillingSpendView'
import { BillingUsage } from './BillingUsage'
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
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)

    // The usage/spend dashboards are intentionally hidden from large orgs (the breakdown queries are
    // slow there) via this flag. Force the overview when it's off so these orgs land on the same
    // simple billing page regardless of how they navigated in.
    const usageSpendDashboardsEnabled = !!featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]

    const rawSection: BillingSectionId = location.pathname.includes('spend')
        ? 'spend'
        : location.pathname.includes('usage')
          ? 'usage'
          : 'overview'

    const section: BillingSectionId = usageSpendDashboardsEnabled ? rawSection : 'overview'

    // Normalise the URL for flag-off orgs that deep-link straight to a usage/spend section. Wait for
    // flags to actually load (they're persisted, so could be stale) before redirecting, so a flag-on
    // user isn't bounced off their section while flags are still resolving.
    useEffect(() => {
        if (receivedFeatureFlags && !usageSpendDashboardsEnabled && rawSection !== 'overview') {
            router.actions.replace(urls.organizationBillingSection('overview'), searchParams)
        }
    }, [receivedFeatureFlags, usageSpendDashboardsEnabled, rawSection, searchParams])

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
            {usageSpendDashboardsEnabled && <LemonTabs activeKey={section} onChange={handleTabChange} tabs={tabs} />}

            {section === 'overview' && <Billing />}
            {section === 'usage' && <BillingUsage />}
            {section === 'spend' && <BillingSpendView />}
        </div>
    )
}
