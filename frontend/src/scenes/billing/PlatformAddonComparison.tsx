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
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { BillingPlan, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

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
// comparison lives in the collapsible sections below.
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

const OTHER_SECTION = 'Other features'

// Ordered section list — features are placed in the first section whose keys match.
// Any feature not matched falls through to OTHER_SECTION, which renders last.
const SECTION_DEFINITIONS: { section: string; featureKeys: string[] }[] = [
    {
        section: 'Security & access',
        featureKeys: [
            'access_control',
            'advanced_permissions',
            'role_based_access',
            'social_sso',
            'saml',
            'scim',
            'sso_enforcement',
            '2fa',
            '2fa_enforcement',
            'automatic_provisioning',
            'organization_security_settings',
        ],
    },
    {
        section: 'Compliance & governance',
        featureKeys: [
            'hipaa_baa',
            'custom_msa',
            'security_assessment',
            'audit_logs',
            'approvals',
            'terms_and_conditions',
        ],
    },
    {
        section: 'Support',
        featureKeys: [
            'community_support',
            'email_support',
            'dedicated_support',
            'priority_support',
            'support_response_time',
            'account_manager',
            'training',
            'configuration_support',
        ],
    },
    {
        section: 'Collaboration & branding',
        featureKeys: [
            'organizations_projects',
            'team_members',
            'organization_invite_settings',
            'white_labelling',
            'data_color_themes',
        ],
    },
]

const sectionForFeature = (featureKey: string, featureCategory?: string | null): string => {
    if (featureCategory) {
        return featureCategory
    }
    const match = SECTION_DEFINITIONS.find((s) => s.featureKeys.includes(featureKey))
    return match?.section ?? OTHER_SECTION
}

type ComparisonFeature = {
    key: string
    name: string
    description?: string | null
    section: string
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
                    section: sectionForFeature(feature.key, feature.category),
                    includedIn: new Set([addon.type]),
                })
            }
        })
    })
    return Array.from(features.values())
}

const SECTION_ORDER = [...SECTION_DEFINITIONS.map((s) => s.section), OTHER_SECTION]

const groupBySection = (features: ComparisonFeature[]): { section: string; features: ComparisonFeature[] }[] => {
    const sections = new Map<string, ComparisonFeature[]>()
    features.forEach((feature) => {
        const bucket = sections.get(feature.section) ?? []
        bucket.push(feature)
        sections.set(feature.section, bucket)
    })
    // Order known sections first, then any extras (e.g. backend-provided categories) alphabetically.
    const knownSections = SECTION_ORDER.filter((name) => sections.has(name))
    const extraSections = Array.from(sections.keys())
        .filter((name) => !SECTION_ORDER.includes(name))
        .sort()
    return [...knownSections, ...extraSections].map((name) => ({
        section: name,
        features: sections.get(name) as ComparisonFeature[],
    }))
}

const PlanCard = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product: addon }))
    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const coreFeatures = CORE_FEATURES[addon.type] || []
    const tagline = PLAN_TAGLINES[addon.type]

    return (
        <div
            className={
                'flex flex-col gap-3 p-4 rounded border bg-surface-primary ' +
                (addon.subscribed ? 'border-accent' : 'border-primary')
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
                        <LemonTag key={feature.label} type="muted" size="small" icon={feature.icon}>
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
                <BillingProductAddonActions addon={addon} buttonSize="small" />
            </div>
        </div>
    )
}

const FeatureCell = ({ included, note }: { included: boolean; note?: string | null }): JSX.Element => {
    if (!included) {
        return <IconMinus className="text-muted text-lg" />
    }
    return (
        <span className="flex items-center justify-center gap-1 text-success">
            <IconCheckCircle className="text-lg" />
            {note && <span className="text-secondary text-xs">{note}</span>}
        </span>
    )
}

const ComparisonSection = ({
    features,
    addons,
}: {
    features: ComparisonFeature[]
    addons: BillingProductV2AddonType[]
}): JSX.Element => {
    const gridColsStyle = { gridTemplateColumns: `minmax(200px, 1.5fr) repeat(${addons.length}, 1fr)` }

    return (
        <div>
            {features.map((feature, idx) => (
                <div
                    key={feature.key}
                    className="grid items-center border-t border-primary"
                    style={{
                        ...gridColsStyle,
                        backgroundColor: idx % 2 === 0 ? undefined : 'var(--bg-surface-secondary)',
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
                    {addons.map((addon) => (
                        <div key={addon.type} className="p-3 flex items-center justify-center border-l border-primary">
                            <FeatureCell included={feature.includedIn.has(addon.type)} />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )
}

export const PlatformAddonComparison = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const comparableAddons = useMemo(
        () =>
            COMPARISON_ADDONS.map((type) =>
                product.addons?.find((addon) => addon.type === type && !addon.legacy_product)
            ).filter((addon): addon is BillingProductV2AddonType => !!addon),
        [product.addons]
    )

    const sections = useMemo(() => {
        const features = buildComparisonFeatures(comparableAddons)
        return groupBySection(features)
    }, [comparableAddons])

    if (comparableAddons.length === 0) {
        return null
    }

    const hasPlatformAddon = comparableAddons.some((addon) => addon.subscribed)
    const totalFeatures = sections.reduce((acc, s) => acc + s.features.length, 0)

    const gridColsStyle = {
        gridTemplateColumns: `minmax(200px, 1.5fr) repeat(${comparableAddons.length}, 1fr)`,
    }

    const comparisonTable = (
        <div className="border-t border-primary">
            {sections.map(({ section, features }) => (
                <div key={section}>
                    {/* Section separator */}
                    <div className="grid bg-surface-secondary border-b border-primary" style={gridColsStyle}>
                        <div className="px-3 py-2 text-xs uppercase font-semibold text-secondary tracking-wide">
                            {section}
                        </div>
                        {comparableAddons.map((addon) => (
                            <div key={addon.type} className="border-l border-primary" />
                        ))}
                    </div>
                    <ComparisonSection features={features} addons={comparableAddons} />
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
            {sections.length > 0 && (
                <LemonCollapse
                    defaultActiveKey={hasPlatformAddon ? undefined : 'compare'}
                    panels={[
                        {
                            key: 'compare',
                            header: (
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold">Compare all features</span>
                                    <span className="text-secondary text-xs font-normal">
                                        {totalFeatures} {totalFeatures === 1 ? 'feature' : 'features'} across{' '}
                                        {sections.length} {sections.length === 1 ? 'section' : 'sections'}
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
