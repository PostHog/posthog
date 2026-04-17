import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheckCircle, IconMinus } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { BillingPlan, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { formatFlatRate } from './BillingProductAddon'
import { BillingProductAddonActions } from './BillingProductAddonActions'
import { billingProductLogic } from './billingProductLogic'

const COMPARISON_ADDONS: string[] = [BillingPlan.Boost, BillingPlan.Scale, BillingPlan.Enterprise]

// Brief positioning copy mirroring the pricing page "who are we building for" framing.
// Shown only when the addon's own description is missing.
const FALLBACK_ADDON_TAGLINES: Record<string, string> = {
    [BillingPlan.Boost]: 'For early-stage startups that want a little extra support and collaboration.',
    [BillingPlan.Scale]: 'For scaling teams that need advanced permissioning and higher usage ceilings.',
    [BillingPlan.Enterprise]: 'For larger organizations that need SSO, audit logs, and dedicated support.',
}

type ComparisonFeature = {
    key: string
    name: string
    description?: string | null
    includedIn: Set<string>
}

const buildComparisonFeatures = (addons: BillingProductV2AddonType[]): ComparisonFeature[] => {
    const features = new Map<string, ComparisonFeature>()
    addons.forEach((addon) => {
        addon.features?.forEach((feature) => {
            if (feature.entitlement_only) {
                return
            }
            const existing = features.get(feature.key)
            if (existing) {
                existing.includedIn.add(addon.type)
            } else {
                features.set(feature.key, {
                    key: feature.key,
                    name: feature.name,
                    description: feature.description,
                    includedIn: new Set([addon.type]),
                })
            }
        })
    })
    return Array.from(features.values())
}

const AddonHeader = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product: addon }))
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const flatRate = upgradePlan?.flat_rate
        ? formatFlatRate(Number(upgradePlan.unit_amount_usd), upgradePlan.unit)
        : null

    return (
        <div className="flex flex-col gap-2 p-3 border-r last:border-r-0 border-primary">
            <div className="flex items-center gap-2">
                <h4 className="mb-0 font-bold">{addon.name}</h4>
                {addon.subscribed && (
                    <LemonTag type="primary" icon={<IconCheckCircle />}>
                        Subscribed
                    </LemonTag>
                )}
            </div>
            <p className="text-sm text-secondary m-0 min-h-10">
                {addon.description || FALLBACK_ADDON_TAGLINES[addon.type] || ''}
            </p>
            {flatRate && <div className="text-sm font-semibold">{flatRate}</div>}
            <div className="mt-1">
                <BillingProductAddonActions addon={addon} buttonSize="small" />
            </div>
        </div>
    )
}

export const PlatformAddonComparison = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { billing } = useValues(billingLogic)

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

    // Default open when the user has no active subscription or no platform addon, so they can still discover the features easily.
    const hasPlatformAddon = comparableAddons.some((addon) => addon.subscribed)
    const defaultExpanded = !hasPlatformAddon && billing?.has_active_subscription !== false

    const gridColsStyle = { gridTemplateColumns: `minmax(220px, 1.5fr) repeat(${comparableAddons.length}, 1fr)` }

    const tableContent = (
        <div className="border border-primary rounded overflow-hidden">
            {/* Addon headers */}
            <div className="grid border-b border-primary bg-surface-secondary" style={gridColsStyle}>
                <div className="p-3 flex items-end">
                    <span className="text-xs uppercase text-secondary font-semibold">Feature</span>
                </div>
                {comparableAddons.map((addon) => (
                    <AddonHeader key={addon.type} addon={addon} />
                ))}
            </div>

            {/* Feature rows */}
            {features.map((feature, idx) => (
                <div
                    key={feature.key}
                    className="grid items-center border-b last:border-b-0 border-primary"
                    style={{
                        ...gridColsStyle,
                        backgroundColor: idx % 2 === 0 ? undefined : 'var(--bg-surface-primary)',
                    }}
                >
                    <div className="p-3 text-sm">
                        {feature.description ? (
                            <Tooltip title={feature.description}>
                                <span className="font-medium">{feature.name}</span>
                            </Tooltip>
                        ) : (
                            <span className="font-medium">{feature.name}</span>
                        )}
                    </div>
                    {comparableAddons.map((addon) => (
                        <div key={addon.type} className="p-3 flex items-center justify-center border-l border-primary">
                            {feature.includedIn.has(addon.type) ? (
                                <IconCheckCircle className="text-success text-lg" />
                            ) : (
                                <IconMinus className="text-muted text-lg" />
                            )}
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )

    return (
        <LemonCollapse
            defaultActiveKey={defaultExpanded ? 'compare' : undefined}
            panels={[
                {
                    key: 'compare',
                    header: (
                        <div className="flex items-center gap-2">
                            <span className="font-bold">Compare add-ons</span>
                            <span className="text-secondary text-sm font-normal">
                                Boost, Scale, and Enterprise — see which fits your team
                            </span>
                        </div>
                    ),
                    content: <div className="pt-2">{tableContent}</div>,
                },
            ]}
        />
    )
}
