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

type CoreFeature = { icon: JSX.Element; label: string }

const COMPARISON_PLANS: Partial<Record<BillingPlan, { description: string; coreFeatures: CoreFeature[] }>> = {
    [BillingPlan.Boost]: {
        description: 'Essentials for security and compliance',
        coreFeatures: [
            { icon: <IconLock />, label: 'Access control' },
            { icon: <IconInfinity />, label: 'Unlimited projects' },
            { icon: <IconShieldLock />, label: 'SSO & 2FA enforcement' },
            { icon: <IconShield />, label: 'HIPAA BAA' },
        ],
    },
    [BillingPlan.Scale]: {
        description: 'Everything in Boost plus',
        coreFeatures: [
            { icon: <IconActivity />, label: 'Team activity logs' },
            { icon: <IconCheckCircle />, label: 'Approvals' },
            { icon: <IconShieldLock />, label: 'SAML' },
            { icon: <IconHeadset />, label: 'Priority support' },
        ],
    },
    [BillingPlan.Enterprise]: {
        description: 'Everything in Scale plus',
        coreFeatures: [
            { icon: <IconShieldPeople />, label: 'Role-based access control' },
            { icon: <IconGroups />, label: 'SCIM' },
            { icon: <IconCrown />, label: 'Dedicated account manager' },
        ],
    },
}

type ComparisonFeature = {
    key: string
    name: string
    description?: string | null
    includedIn: Map<string, BillingFeatureType>
}

const PlanCard = ({
    addon,
    onExpandCompare,
}: {
    addon: BillingProductV2AddonType
    onExpandCompare: () => void
}): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const pricedPlan = addon.plans?.find((p) => p.flat_rate)
    const plan = COMPARISON_PLANS[addon.type as BillingPlan]
    const coreFeatures = plan?.coreFeatures ?? []
    const description = plan?.description
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
                <BillingProductAddonActions addon={addon} buttonSize="small" align="left" hidePricingNote />
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

const ComparisonTable = ({
    addons,
    features,
}: {
    addons: BillingProductV2AddonType[]
    features: ComparisonFeature[]
}): JSX.Element => {
    const gridStyle = {
        gridTemplateColumns: `minmax(320px, 3fr) repeat(${addons.length}, minmax(120px, 1fr))`,
    }

    return (
        <div>
            <div className="grid" style={gridStyle}>
                <div className="px-4 py-4 text-sm font-semibold text-secondary">Feature</div>
                {addons.map((addon) => (
                    <div
                        key={addon.type}
                        className="px-4 py-4 text-sm font-semibold text-secondary text-center border-l border-primary"
                    >
                        {addon.name}
                    </div>
                ))}
            </div>
            {features.map((feature) => (
                <div key={feature.key} className="grid border-t border-primary" style={gridStyle}>
                    <div className="px-4 py-4">
                        <div className="text-sm font-semibold">{feature.name}</div>
                        {feature.description && (
                            <div className="text-xs text-secondary mt-1">{feature.description}</div>
                        )}
                    </div>
                    {addons.map((addon) => (
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
}

export const PlatformAddonComparison = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const comparableAddons = (Object.keys(COMPARISON_PLANS) as BillingPlan[])
        .map((type) => product.addons?.find((addon) => addon.type === type && !addon.legacy_product))
        .filter((addon): addon is BillingProductV2AddonType => !!addon)
    const legacyAddon = product.addons?.find((addon) => addon.legacy_product && addon.subscribed) ?? null
    const hasPlatformAddon = comparableAddons.some((addon) => addon.subscribed)
    const [isCompareOpen, setIsCompareOpen] = useState(hasPlatformAddon || !!legacyAddon)

    if (comparableAddons.length === 0) {
        return null
    }

    const tableAddons = legacyAddon ? [legacyAddon, ...comparableAddons] : comparableAddons

    // Features appear in the order the backend returns them (boost → scale-only → enterprise-only).
    const featuresByKey = new Map<string, ComparisonFeature>()
    tableAddons.forEach((addon) => {
        addon.features?.forEach((feature) => {
            if (feature.entitlement_only) {
                return
            }
            const existing = featuresByKey.get(feature.key)
            if (existing) {
                existing.includedIn.set(addon.type, feature)
            } else {
                featuresByKey.set(feature.key, {
                    key: feature.key,
                    name: feature.name,
                    description: feature.description,
                    includedIn: new Map([[addon.type, feature]]),
                })
            }
        })
    })
    const features = Array.from(featuresByKey.values())

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
                            content: <ComparisonTable addons={tableAddons} features={features} />,
                        },
                    ]}
                />
            )}
        </div>
    )
}
