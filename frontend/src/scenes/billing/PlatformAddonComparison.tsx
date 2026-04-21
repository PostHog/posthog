import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    IconActivity,
    IconCheckCircle,
    IconCrown,
    IconGroups,
    IconHeadset,
    IconInfinity,
    IconLock,
    IconShield,
    IconShieldLock,
    IconShieldPeople,
} from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { humanFriendlyCurrency, toSentenceCase } from 'lib/utils'

import { BillingFeatureType, BillingPlan, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { BillingProductAddonActions } from './BillingProductAddonActions'
import { billingProductLogic } from './billingProductLogic'
import { PlanIcon } from './PlanComparison'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export const COMPARISON_ADDONS: BillingPlan[] = [BillingPlan.Boost, BillingPlan.Scale, BillingPlan.Enterprise]

const PLAN_DESCRIPTION: Partial<Record<BillingPlan, string>> = {
    [BillingPlan.Boost]: 'Essentials for security and compliance',
    [BillingPlan.Scale]: 'Everything in Boost plus',
    [BillingPlan.Enterprise]: 'Everything in Scale plus',
}

type CoreFeature = { icon: JSX.Element; label: string }
const CORE_FEATURES: Partial<Record<BillingPlan, CoreFeature[]>> = {
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

const PlanCard = ({
    addon,
    onExpandCompare,
}: {
    addon: BillingProductV2AddonType
    onExpandCompare: () => void
}): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product: addon }))
    // Fall back to currentPlan when the addon is subscribed — upgradePlan is null on the current tier.
    const pricedPlan = currentAndUpgradePlans?.upgradePlan ?? currentAndUpgradePlans?.currentPlan
    const coreFeatures = CORE_FEATURES[addon.type as BillingPlan] || []
    const description = PLAN_DESCRIPTION[addon.type as BillingPlan]
    const isOnTrial = billing?.trial?.target === addon.type

    return (
        <div
            className={clsx(
                'flex flex-col gap-3 p-5 rounded bg-surface-secondary',
                (addon.subscribed || isOnTrial) && 'ring-1 ring-accent'
            )}
        >
            <div>
                <div className="flex items-center gap-x-2">
                    <h4 className="mb-0 font-bold">{addon.name}</h4>
                    {addon.subscribed && <LemonTag type="primary">Subscribed</LemonTag>}
                    {isOnTrial && (
                        <Tooltip
                            title={
                                <p>
                                    You are currently on a free trial for{' '}
                                    <b>{toSentenceCase(billing?.trial?.target || '')}</b> until{' '}
                                    <b>{dayjs(billing?.trial?.expires_at).format('LL')}</b>. At the end of the trial{' '}
                                    {billing?.trial?.type === 'autosubscribe'
                                        ? 'you will be automatically subscribed to the plan.'
                                        : 'you will be asked to subscribe. If you choose not to, you will lose access to the features.'}
                                </p>
                            }
                        >
                            <LemonTag type="completion">You're on a trial</LemonTag>
                        </Tooltip>
                    )}
                </div>
                {description && <div>{description}</div>}
            </div>
            {coreFeatures.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    {coreFeatures.map((feature) => (
                        <LemonTag key={feature.label} icon={feature.icon}>
                            {feature.label}
                        </LemonTag>
                    ))}
                    <Link className="text-xs ml-1" onClick={onExpandCompare}>
                        + More
                    </Link>
                </div>
            )}
            {pricedPlan?.flat_rate && (
                <div className="flex items-baseline gap-x-1 mt-1">
                    <span className="font-bold text-3xl leading-none">
                        {humanFriendlyCurrency(Number(pricedPlan.unit_amount_usd), 0)}
                    </span>
                    {pricedPlan.unit && <span className="text-secondary">/ {pricedPlan.unit}</span>}
                </div>
            )}
            <div className="-mt-2">
                <BillingProductAddonActions
                    addon={addon}
                    buttonSize="small"
                    align="left"
                    hideTrialTag
                    hidePricingNote
                />
            </div>
        </div>
    )
}

const LegacyPlanHero = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { currentAndUpgradePlans, surveyID } = useValues(billingProductLogic({ product: addon }))
    const { reportSurveyShown, setSurveyResponse } = useActions(billingProductLogic({ product: addon }))
    const currentPlan = currentAndUpgradePlans?.currentPlan

    return (
        <div className="flex flex-col gap-3 p-5 rounded bg-surface-secondary ring-1 ring-accent">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <div className="flex items-center gap-x-2">
                        <h4 className="mb-0 font-bold">{addon.name}</h4>
                        <LemonTag type="primary">Subscribed</LemonTag>
                        <LemonTag type="warning">Legacy</LemonTag>
                    </div>
                    <div>
                        You're subscribed to our legacy {addon.name} plan. Compare plans to see if it makes sense to
                        switch.
                    </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 self-center">
                    {currentPlan?.flat_rate && (
                        <div className="flex items-baseline gap-x-1">
                            <span className="font-bold text-3xl leading-none">
                                {humanFriendlyCurrency(Number(currentPlan.unit_amount_usd), 0)}
                            </span>
                            {currentPlan.unit && <span className="text-secondary">/ {currentPlan.unit}</span>}
                        </div>
                    )}
                    <More
                        overlay={
                            <LemonButton
                                fullWidth
                                onClick={() => {
                                    setSurveyResponse('$survey_response_1', addon.type)
                                    reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, addon.type)
                                }}
                            >
                                Remove add-on
                            </LemonButton>
                        }
                    />
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
    const legacyAddon = product.addons?.find((addon) => addon.legacy_product && addon.subscribed) ?? null
    const hasPlatformAddon = comparableAddons.some((addon) => addon.subscribed)
    const [isCompareOpen, setIsCompareOpen] = useState(hasPlatformAddon || !!legacyAddon)

    if (comparableAddons.length === 0) {
        return null
    }

    const tableAddons = legacyAddon ? [legacyAddon, ...comparableAddons] : comparableAddons
    const features = buildComparisonFeatures(tableAddons)

    const tableGridStyle = {
        gridTemplateColumns: `minmax(320px, 3fr) repeat(${tableAddons.length}, minmax(120px, 1fr))`,
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
                    <PlanCard key={addon.type} addon={addon} onExpandCompare={() => setIsCompareOpen(true)} />
                ))}
            </div>

            {features.length > 0 && (
                <LemonCollapse
                    activeKey={isCompareOpen ? 'compare' : null}
                    onChange={(key) => setIsCompareOpen(key === 'compare')}
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
