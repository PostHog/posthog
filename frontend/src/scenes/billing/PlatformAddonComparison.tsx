import { useValues } from 'kea'
import { useMemo } from 'react'

import {
    IconActivity,
    IconCheckCircle,
    IconCrown,
    IconGroups,
    IconHeadset,
    IconInfinity,
    IconLock,
    IconMinus,
    IconShield,
    IconShieldLock,
    IconShieldPeople,
} from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { BillingPlan, BillingFeatureType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { formatFlatRate } from './BillingProductAddon'
import { BillingProductAddonActions } from './BillingProductAddonActions'
import { billingProductLogic } from './billingProductLogic'

const COMPARISON_ADDONS: string[] = [BillingPlan.Boost, BillingPlan.Scale, BillingPlan.Enterprise]

// Short "who it's for" strap-lines (max 5 words) shown under the plan name.
const PLAN_TAGLINES: Record<string, string> = {
    [BillingPlan.Boost]: 'For early-stage startups',
    [BillingPlan.Scale]: 'For scaling teams',
    [BillingPlan.Enterprise]: 'For larger organizations',
}

// Core feature highlights shown as tags on each plan card.
// These are marketing call-outs, not an exhaustive feature list — the full
// comparison lives in the collapsible table below.
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
}

type ComparisonFeature = {
    key: string
    name: string
    description?: string | null
    // For each addon.type → either the feature object for cell content (limit, unit, note) or absent.
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
            className={
                'flex flex-col gap-3 p-4 rounded bg-surface-secondary ' +
                (addon.subscribed ? 'ring-2 ring-accent' : '')
            }
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
                <div className="text-base font-bold mt-auto">
                    {formatFlatRate(Number(upgradePlan.unit_amount_usd), upgradePlan.unit)}
                </div>
            )}
            <div>
                <BillingProductAddonActions addon={addon} buttonSize="small" align="left" />
            </div>
        </div>
    )
}

const formatCellValue = (feature: BillingFeatureType | undefined): JSX.Element => {
    if (!feature) {
        return <IconMinus className="text-muted text-lg" />
    }
    if (feature.note) {
        return <span className="text-sm">{feature.note}</span>
    }
    if (feature.limit != null) {
        return (
            <span className="text-sm">
                {feature.limit}
                {feature.unit ? ` ${feature.unit}` : ''}
            </span>
        )
    }
    return <IconCheckCircle className="text-success text-lg" />
}

export const PlatformAddonComparison = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const comparableAddons = useMemo(
        () =>
            COMPARISON_ADDONS.map((type) =>
                product.addons?.find((addon) => addon.type === type && !addon.legacy_product)
            ).filter((addon): addon is BillingProductV2AddonType => !!addon),
        [product.addons]
    )

    const features = useMemo(() => buildComparisonFeatures(comparableAddons), [comparableAddons])

    if (comparableAddons.length === 0) {
        return null
    }

    const hasPlatformAddon = comparableAddons.some((addon) => addon.subscribed)

    const gridColsStyle = {
        gridTemplateColumns: `minmax(240px, 1.5fr) repeat(${comparableAddons.length}, 1fr)`,
    }

    const comparisonTable = (
        <div>
            {/* Header row */}
            <div className="grid" style={gridColsStyle}>
                <div className="px-4 py-4 text-sm font-semibold text-secondary">Feature</div>
                {comparableAddons.map((addon) => (
                    <div
                        key={addon.type}
                        className="px-4 py-4 text-sm font-semibold text-secondary text-center border-l border-primary"
                    >
                        {addon.name}
                    </div>
                ))}
            </div>
            {/* Feature rows */}
            {features.map((feature) => (
                <div key={feature.key} className="grid border-t border-primary" style={gridColsStyle}>
                    <div className="px-4 py-4">
                        <div className="text-sm font-semibold">{feature.name}</div>
                        {feature.description && (
                            <div className="text-xs text-secondary mt-1">{feature.description}</div>
                        )}
                    </div>
                    {comparableAddons.map((addon) => (
                        <div
                            key={addon.type}
                            className="px-4 py-4 flex items-center justify-center text-center border-l border-primary"
                        >
                            {formatCellValue(feature.includedIn.get(addon.type))}
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )

    return (
        <div className="flex flex-col gap-4">
            {/* Plan cards */}
            <div
                className="grid gap-3"
                style={{ gridTemplateColumns: `repeat(${comparableAddons.length}, minmax(0, 1fr))` }}
            >
                {comparableAddons.map((addon) => (
                    <PlanCard key={addon.type} addon={addon} />
                ))}
            </div>

            {/* Single collapsible comparison table */}
            {features.length > 0 && (
                <LemonCollapse
                    defaultActiveKey={hasPlatformAddon ? undefined : 'compare'}
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
