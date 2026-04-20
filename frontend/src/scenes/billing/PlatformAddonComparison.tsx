import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import {
    IconAI,
    IconActivity,
    IconCheckCircle,
    IconCrown,
    IconGear,
    IconGroups,
    IconHeadset,
    IconInfinity,
    IconLock,
    IconServer,
    IconShield,
    IconShieldLock,
    IconShieldPeople,
} from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { humanFriendlyCurrency } from 'lib/utils'

import { BillingFeatureType, BillingPlan, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { BillingProductAddonActions } from './BillingProductAddonActions'
import { billingProductLogic } from './billingProductLogic'
import { PlanIcon } from './PlanComparison'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const COMPARISON_ADDONS: BillingPlan[] = [BillingPlan.Boost, BillingPlan.Scale, BillingPlan.Enterprise]

const PLAN_TAGLINES: Record<string, string> = {
    [BillingPlan.Boost]: 'For early-stage startups',
    [BillingPlan.Scale]: 'For scaling teams',
    [BillingPlan.Enterprise]: 'For larger organizations',
}

type CoreFeature = { icon: JSX.Element; label: string }
const CORE_FEATURES: Record<string, CoreFeature[]> = {
    [BillingPlan.Boost]: [
        { icon: <IconLock />, label: 'Access control' },
        { icon: <IconInfinity />, label: 'Unlimited projects' },
        { icon: <IconShieldLock />, label: 'SSO & 2FA enforcement' },
        { icon: <IconShield />, label: 'HIPAA BAA' },
    ],
    [BillingPlan.Scale]: [
        { icon: <IconActivity />, label: 'Team activity logs' },
        { icon: <IconCheckCircle />, label: 'Approvals' },
        { icon: <IconShieldLock />, label: 'SAML' },
        { icon: <IconHeadset />, label: 'Priority support' },
    ],
    [BillingPlan.Enterprise]: [
        { icon: <IconShieldPeople />, label: 'Role-based access control' },
        { icon: <IconGroups />, label: 'SCIM' },
        { icon: <IconCrown />, label: 'Dedicated account manager' },
    ],
    [BillingPlan.Teams]: [
        { icon: <IconGear />, label: 'Automatic provisioning' },
        { icon: <IconServer />, label: 'Managed reverse proxy' },
        { icon: <IconAI />, label: 'Product Analytics AI' },
        { icon: <IconShieldLock />, label: 'Enforce SSO login' },
        { icon: <IconLock />, label: 'Enforce 2FA' },
        { icon: <IconHeadset />, label: 'Priority support' },
    ],
}

type ComparisonFeature = {
    key: string
    name: string
    description?: string | null
    includedIn: Map<string, BillingFeatureType>
}

const buildComparisonFeatures = (addons: BillingProductV2AddonType[]): ComparisonFeature[] => {
    // Preserve insertion order so features appear in the same order they're returned
    // by the backend (boost first, then scale-only, then enterprise-only).
    const features = new Map<string, ComparisonFeature>()
    addons.forEach((addon) => {
        addon.features?.forEach((feature) => {
            if (feature.entitlement_only) {
                return
            }
            const existing = features.get(feature.key)
            if (existing) {
                existing.includedIn.set(addon.type, feature)
            } else {
                features.set(feature.key, {
                    key: feature.key,
                    name: feature.name,
                    description: feature.description,
                    includedIn: new Map([[addon.type, feature]]),
                })
            }
        })
    })
    return Array.from(features.values())
}

const PlanCard = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product: addon }))
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const coreFeatures = CORE_FEATURES[addon.type] || []
    const tagline = PLAN_TAGLINES[addon.type]

    return (
        <div
            className={clsx(
                'flex flex-col gap-3 p-5 rounded bg-surface-secondary',
                addon.subscribed && 'ring-2 ring-accent'
            )}
        >
            <div className="flex items-center gap-2">
                <h4 className="mb-0 font-bold">{addon.name}</h4>
                {addon.subscribed && (
                    <LemonTag type="primary" icon={<IconCheckCircle />}>
                        Subscribed
                    </LemonTag>
                )}
            </div>
            {tagline && <p className="text-sm text-secondary m-0">{tagline}</p>}
            {coreFeatures.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {coreFeatures.map((feature) => (
                        <LemonTag key={feature.label} icon={feature.icon}>
                            {feature.label}
                        </LemonTag>
                    ))}
                </div>
            )}
            {upgradePlan?.flat_rate && (
                <div className="flex items-baseline gap-x-1 mt-1">
                    <span className="font-bold text-3xl leading-none">
                        {humanFriendlyCurrency(Number(upgradePlan.unit_amount_usd), 0)}
                    </span>
                    {upgradePlan.unit && <span className="text-secondary">/ {upgradePlan.unit}</span>}
                </div>
            )}
            <div className="-mt-2">
                <BillingProductAddonActions addon={addon} buttonSize="small" align="left" />
            </div>
        </div>
    )
}

const LegacyPlanHero = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { currentAndUpgradePlans, surveyID } = useValues(billingProductLogic({ product: addon }))
    const { reportSurveyShown, setSurveyResponse } = useActions(billingProductLogic({ product: addon }))
    const currentPlan = currentAndUpgradePlans?.currentPlan
    const coreFeatures = CORE_FEATURES[addon.type] ?? []

    return (
        <div className="flex flex-col gap-3 p-5 rounded bg-surface-secondary ring-2 ring-accent">
            <div className="flex items-start justify-between gap-4">
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                        <h4 className="mb-0 font-bold">{addon.name}</h4>
                        <LemonTag type="primary" icon={<IconCheckCircle />}>
                            Subscribed
                        </LemonTag>
                        <LemonTag type="warning">Legacy</LemonTag>
                    </div>
                    <p className="text-sm text-secondary m-0">
                        You're subscribed to our legacy {addon.name} plan. Compare plans to see if it makes sense to
                        switch.
                    </p>
                    {coreFeatures.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                            {coreFeatures.map((feature) => (
                                <LemonTag key={feature.label} icon={feature.icon}>
                                    {feature.label}
                                </LemonTag>
                            ))}
                        </div>
                    )}
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                    {currentPlan?.flat_rate && (
                        <div className="flex items-baseline gap-x-1">
                            <span className="font-bold text-3xl leading-none">
                                {humanFriendlyCurrency(Number(currentPlan.unit_amount_usd), 0)}
                            </span>
                            {currentPlan.unit && <span className="text-secondary">/ {currentPlan.unit}</span>}
                        </div>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            setSurveyResponse('$survey_response_1', addon.type)
                            reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, addon.type)
                        }}
                    >
                        Remove add-on
                    </LemonButton>
                </div>
            </div>
            {surveyID === UNSUBSCRIBE_SURVEY_ID && <UnsubscribeSurveyModal product={addon} />}
        </div>
    )
}

export const PlatformAddonComparison = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const comparableAddons = COMPARISON_ADDONS.map((type) =>
        product.addons?.find((addon) => addon.type === type && !addon.legacy_product)
    ).filter((addon): addon is BillingProductV2AddonType => !!addon)

    if (comparableAddons.length === 0) {
        return null
    }

    const legacyAddon = product.addons?.find((addon) => addon.legacy_product && addon.subscribed) ?? null
    const tableAddons = legacyAddon ? [legacyAddon, ...comparableAddons] : comparableAddons
    const features = buildComparisonFeatures(tableAddons)
    const hasPlatformAddon = comparableAddons.some((addon) => addon.subscribed)

    const tableGridStyle = {
        gridTemplateColumns: `minmax(240px, 1.5fr) repeat(${tableAddons.length}, 1fr)`,
    }

    const comparisonTable = (
        <div>
            <div className="grid" style={tableGridStyle}>
                <div className="px-4 py-4 text-sm font-semibold text-secondary">Feature</div>
                {tableAddons.map((addon) => (
                    <div
                        key={addon.type}
                        className="px-4 py-4 text-sm font-semibold text-secondary text-center border-l border-primary"
                    >
                        {addon.name}
                    </div>
                ))}
            </div>
            {features.map((feature) => (
                <div key={feature.key} className="grid border-t border-primary" style={tableGridStyle}>
                    <div className="px-4 py-4">
                        <div className="text-sm font-semibold">{feature.name}</div>
                        {feature.description && (
                            <div className="text-xs text-secondary mt-1">{feature.description}</div>
                        )}
                    </div>
                    {tableAddons.map((addon) => (
                        <div
                            key={addon.type}
                            className="px-4 py-4 flex items-center justify-center border-l border-primary"
                        >
                            <PlanIcon feature={feature.includedIn.get(addon.type)} />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )

    return (
        <div className="flex flex-col gap-4">
            {legacyAddon && <LegacyPlanHero addon={legacyAddon} />}

            <div className="grid gap-3 grid-cols-3">
                {comparableAddons.map((addon) => (
                    <PlanCard key={addon.type} addon={addon} />
                ))}
            </div>

            {features.length > 0 && (
                <LemonCollapse
                    defaultActiveKey={hasPlatformAddon || legacyAddon ? 'compare' : undefined}
                    panels={[
                        {
                            key: 'compare',
                            header: (
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold">Compare all features</span>
                                    <span className="text-secondary text-xs font-normal">
                                        {features.length} {features.length === 1 ? 'feature' : 'features'}
                                    </span>
                                </div>
                            ),
                            content: comparisonTable,
                        },
                    ]}
                />
            )}
        </div>
    )
}
