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
    IconX,
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

const PlanPrice = ({
    addon,
    unit_amount_usd,
    unit_label,
}: {
    addon: BillingProductV2AddonType
    unit_amount_usd: string | null
    unit_label: string | null
}): JSX.Element => {
    // When the customer is subscribed to a price lower than the product's default price,
    // show the default price as a strikethrough
    const showDiscount = addon.subscribed && addon.default_unit_amount_usd != null && addon.unit_amount_usd != null
    const mainPrice = showDiscount ? addon.unit_amount_usd : unit_amount_usd

    return (
        <div className="flex items-start gap-x-1 mt-1">
            <span className="font-bold text-3xl leading-none">{humanFriendlyCurrency(Number(mainPrice), 0)}</span>
            {showDiscount && (
                <span className="text-secondary line-through self-baseline">
                    {humanFriendlyCurrency(Number(addon.default_unit_amount_usd), 0)}
                </span>
            )}
            {unit_label && <span className="text-secondary self-baseline">/ {unit_label}</span>}
        </div>
    )
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
                <PlanPrice addon={addon} unit_amount_usd={pricedPlan.unit_amount_usd} unit_label={pricedPlan.unit} />
            )}
            <div className="-mt-2">
                <BillingProductAddonActions addon={addon} buttonSize="small" align="left" hidePricingNote />
            </div>
        </div>
    )
}

const LegacyPlanHero = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { surveyID } = useValues(billingProductLogic({ product: addon }))
    const { reportSurveyShown, setSurveyResponse } = useActions(billingProductLogic({ product: addon }))
    const pricedPlan = addon.plans?.find((p) => p.flat_rate)

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
                        You're on our legacy {addon.name} add-on. Compare the new plans below if you'd like to switch.
                    </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 self-center">
                    {pricedPlan?.flat_rate && (
                        <PlanPrice
                            addon={addon}
                            unit_amount_usd={pricedPlan.unit_amount_usd}
                            unit_label={pricedPlan.unit}
                        />
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
                    {addons.map((addon) => {
                        const cellFeature = feature.includedIn.get(addon.type)
                        return (
                            <div
                                key={addon.type}
                                className="px-4 py-4 flex items-center justify-center text-center text-sm border-l border-primary"
                            >
                                {!cellFeature ? (
                                    <IconX className="text-danger text-lg" />
                                ) : cellFeature.note || cellFeature.limit ? (
                                    <div className="flex flex-col items-center gap-y-1">
                                        {cellFeature.note && <span>{cellFeature.note}</span>}
                                        {cellFeature.limit && (
                                            <span>
                                                {cellFeature.limit} {cellFeature.unit}
                                            </span>
                                        )}
                                    </div>
                                ) : (
                                    <IconCheckCircle className="text-success text-lg" />
                                )}
                            </div>
                        )
                    })}
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
    const [isCompareOpen, setIsCompareOpen] = useState(false)

    if (comparableAddons.length === 0) {
        return null
    }

    const tableAddons = legacyAddon ? [legacyAddon, ...comparableAddons] : comparableAddons

    // plan.features is the full inherited superset for each tier.
    // The billing API marks tier-own features with entitlement_only=false and inherited ones with entitlement_only=true
    // TODO: do not show entitlement-only features that are not inherited, such as "Product Analytics AI"
    const featuresByKey = new Map<string, ComparisonFeature>()
    tableAddons.forEach((addon) => {
        const planFeatures = (addon.plans?.find((p) => p.flat_rate) ?? addon.plans?.[0])?.features
        planFeatures?.forEach((feature) => {
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
                    activeKey={isCompareOpen ? 'compare' : undefined}
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
