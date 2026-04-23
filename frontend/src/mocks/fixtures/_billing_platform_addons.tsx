import {
    AvailableFeature,
    BillingFeatureType,
    BillingPlan,
    BillingPlanType,
    BillingProductV2AddonType,
    BillingType,
} from '~/types'

import { billingJson } from './_billing'

type PlatformAddonType = BillingPlan.Boost | BillingPlan.Scale | BillingPlan.Enterprise
const PLATFORM_ADDON_TYPES: readonly PlatformAddonType[] = [
    BillingPlan.Boost,
    BillingPlan.Scale,
    BillingPlan.Enterprise,
]

type AddonPlanFeature = Pick<BillingFeatureType, 'key' | 'name' | 'description' | 'unit' | 'limit' | 'note'>

const feature = (
    key: `${AvailableFeature}`,
    name: string,
    description: string,
    note: string | null = null
): AddonPlanFeature => ({ key, name, description, unit: null, limit: null, note })

const BOOST_FEATURES: AddonPlanFeature[] = [
    feature('access_control', 'Access control', 'Control who can access and modify data and features.'),
    feature('organizations_projects', 'Projects', 'Organize environments within a project.', 'Unlimited'),
    feature('sso_enforcement', 'Enforce SSO login', 'Users can only sign up and log in with your SSO provider.'),
    feature('2fa_enforcement', 'Enforce 2FA', 'Require all users to enable two-factor authentication.'),
    feature('hipaa_baa', 'HIPAA BAA', 'Get a signed HIPAA Business Associate Agreement.'),
    feature('audit_logs', 'Audit logs', 'See who has accessed or modified entities within PostHog.', 'Basic'),
    feature('support_response_time', 'Support response time', 'Get help from our team.', '24 hours'),
]

const SCALE_ONLY_FEATURES: AddonPlanFeature[] = [
    feature('approvals', 'Approvals', 'Require approval before deploying feature flag and experiment changes.'),
    feature('saml', 'SAML SSO', "Allow your organization's users to log in with SAML."),
    feature('priority_support', 'Priority support', 'Get help from our team faster than other customers.'),
    feature('white_labelling', 'White labeling', 'Use your own branding on surveys and shared dashboards.'),
]

const ENTERPRISE_ONLY_FEATURES: AddonPlanFeature[] = [
    feature('role_based_access', 'Role-based access control', 'Control access to features with custom roles.'),
    feature('scim', 'SCIM', 'Automate user provisioning and deprovisioning with SCIM.'),
    feature('dedicated_support', 'Dedicated account manager', 'Work with a dedicated account manager.'),
    feature('custom_msa', 'Custom MSA', 'Get a custom Master Services Agreement tailored to your company.'),
    feature('training', 'Ongoing training', 'Get training from our team to quickly get up and running.'),
]

const withOverrides = (
    source: AddonPlanFeature[],
    overrides: Partial<Record<string, Partial<AddonPlanFeature>>>
): AddonPlanFeature[] => source.map((f) => (overrides[f.key] ? { ...f, ...overrides[f.key] } : f))

const SCALE_FEATURES: AddonPlanFeature[] = [
    ...withOverrides(BOOST_FEATURES, {
        audit_logs: { note: 'Advanced' },
        support_response_time: { note: '12 hours' },
    }),
    ...SCALE_ONLY_FEATURES,
]

const ENTERPRISE_FEATURES: AddonPlanFeature[] = [
    ...withOverrides(SCALE_FEATURES, {
        support_response_time: { note: '4 hours' },
    }),
    ...ENTERPRISE_ONLY_FEATURES,
]

const CATALOG: Record<
    PlatformAddonType,
    { name: string; description: string; price: string; features: AddonPlanFeature[] }
> = {
    [BillingPlan.Boost]: {
        name: 'Boost',
        description: 'Essentials for security and compliance.',
        price: '100.00',
        features: BOOST_FEATURES,
    },
    [BillingPlan.Scale]: {
        name: 'Scale',
        description: 'Advanced controls, approvals, and priority support.',
        price: '450.00',
        features: SCALE_FEATURES,
    },
    [BillingPlan.Enterprise]: {
        name: 'Enterprise',
        description: 'Tailored for large organizations with a dedicated account manager.',
        price: '1500.00',
        features: ENTERPRISE_FEATURES,
    },
}

const makePlatformAddon = (
    type: PlatformAddonType,
    { subscribed, trialEligible }: { subscribed: boolean; trialEligible: boolean }
): BillingProductV2AddonType => {
    const entry = CATALOG[type]
    const plan: BillingPlanType = {
        plan_key: `addon-${type}-20260101`,
        // the platform addon product_keys aren't represented in the ProductKey enum yet
        product_key: type as BillingPlanType['product_key'],
        name: entry.name,
        description: entry.description,
        image_url: null,
        docs_url: 'https://posthog.com/pricing',
        note: null,
        unit: 'month',
        flat_rate: true,
        free_allocation: null,
        features: entry.features,
        tiers: [],
        current_plan: subscribed,
        included_if: null,
        contact_support: null,
        unit_amount_usd: entry.price,
    }
    return {
        name: entry.name,
        description: entry.description,
        price_description: null,
        image_url: null,
        icon_key: 'IconStack',
        docs_url: 'https://posthog.com/pricing',
        type,
        tiers: [],
        tiered: false,
        included_with_main_product: false,
        subscribed,
        inclusion_only: false,
        contact_support: null,
        unit: null,
        display_unit: null,
        display_decimals: null,
        display_divisor: null,
        unit_amount_usd: null,
        current_amount_usd: subscribed ? entry.price : null,
        current_usage: 0,
        projected_usage: 0,
        projected_amount_usd: subscribed ? entry.price : null,
        plans: [plan],
        features: entry.features.map(({ key, name, description }) => ({
            key,
            name,
            description,
            images: null,
            icon_key: null,
            type: null,
        })),
        trial: trialEligible && !subscribed ? { length: 14 } : null,
        legacy_product: false,
        usage_key: undefined,
        usage_limit: null,
    }
}

export type PlatformAddonScenario = 'trial-available' | 'trial-used' | 'on-scale' | 'on-legacy-teams'

export const makeBillingWithPlatformAddons = (scenario: PlatformAddonScenario): BillingType => {
    const platformProduct = billingJson.products.find((p) => p.type === 'platform_and_support')
    if (!platformProduct) {
        return billingJson
    }

    const subscribedType: PlatformAddonType | BillingPlan.Teams | null =
        scenario === 'on-scale'
            ? BillingPlan.Scale
            : scenario === 'on-legacy-teams'
              ? BillingPlan.Teams
              : null
    const trialEligible = scenario === 'trial-available'

    const comparisonAddons = PLATFORM_ADDON_TYPES.map((type) =>
        makePlatformAddon(type, {
            subscribed: subscribedType === type,
            trialEligible,
        })
    )

    const legacyTeamsSource = platformProduct.addons?.find((addon) => addon.type === BillingPlan.Teams)
    const legacyTeams = legacyTeamsSource
        ? {
              ...legacyTeamsSource,
              legacy_product: true,
              subscribed: subscribedType === BillingPlan.Teams,
              current_amount_usd: subscribedType === BillingPlan.Teams ? '450.00' : null,
              projected_amount_usd: subscribedType === BillingPlan.Teams ? '450.00' : null,
          }
        : null

    const addons = [...(legacyTeams ? [legacyTeams] : []), ...comparisonAddons]

    return {
        ...billingJson,
        products: billingJson.products.map((product) =>
            product.type === 'platform_and_support'
                ? {
                      ...product,
                      subscribed: true,
                      addons,
                  }
                : product
        ),
    }
}
