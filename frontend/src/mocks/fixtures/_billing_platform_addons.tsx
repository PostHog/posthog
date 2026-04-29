import {
    AvailableFeature,
    BillingFeatureType,
    BillingPlan,
    BillingPlanType,
    BillingProductV2AddonType,
    BillingType,
} from '~/types'

type AddonType = BillingPlan.Teams | BillingPlan.Boost | BillingPlan.Scale | BillingPlan.Enterprise

type AddonPlanFeature = Pick<
    BillingFeatureType,
    'key' | 'name' | 'description' | 'unit' | 'limit' | 'note' | 'entitlement_only'
>

type FeatureOpts = {
    note?: string
    limit?: number
    unit?: string
    entitlement_only?: boolean
}

const feature = (
    key: `${AvailableFeature}`,
    name: string,
    description: string,
    opts: FeatureOpts = {}
): AddonPlanFeature => ({
    key,
    name,
    description,
    unit: opts.unit ?? null,
    limit: opts.limit ?? null,
    note: opts.note ?? null,
    entitlement_only: opts.entitlement_only,
})

// Descriptions below mirror billing/constants/features/{teams,boost,scale,enterprise}.yml

const projects = feature(
    'organizations_projects',
    'Projects',
    'Organize environments within a project. Share dashboards, insights and more across environments without duplicating work.',
    { note: 'Unlimited' }
)
const ssoEnforcement = feature(
    'sso_enforcement',
    'Enforce SSO login',
    'Users can only sign up and log in to your PostHog organization with your specified SSO provider.'
)
const twoFaEnforcement = feature(
    '2fa_enforcement',
    'Enforce 2FA',
    'Require all users in your organization to enable two-factor authentication.'
)
const whiteLabelling = feature(
    'white_labelling',
    'White labeling',
    'Use your own branding on surveys, shared dashboards, shared insights, and more.'
)
const advancedPermissions = feature(
    'advanced_permissions',
    'Access control',
    'Control who can access and modify data and features within your organization.'
)
const accessControl = feature(
    'access_control',
    'Access control',
    'Control who can access and modify data and features within your organization.',
    { entitlement_only: true }
)
const hipaaBaa = feature(
    'hipaa_baa',
    'HIPAA BAA',
    'Get a signed HIPAA Business Associate Agreement (BAA) to use PostHog in a HIPAA-compliant manner.'
)
const automaticProvisioning = feature(
    'automatic_provisioning',
    'Automatic provisioning',
    'Verify your domains to enforce SSO and automatically add users with matching email addresses to your organization.'
)
const dataColorThemes = feature(
    'data_color_themes',
    'Customizable chart colors',
    'Customize the appearance of insights with color themes.'
)
const organizationInviteSettings = feature(
    'organization_invite_settings',
    'Organization invite settings',
    'Customize who can invite members to your organization.'
)
const organizationSecuritySettings = feature(
    'organization_security_settings',
    'Organization security settings',
    'Configure security permissions for organization members.'
)
const sessionReplayDataRetention = (months: number): AddonPlanFeature =>
    feature(
        'session_replay_data_retention',
        'Session Replay data retention',
        'Keep a historical record of your Session Replay data.',
        { limit: months, unit: 'months' }
    )
const auditLogs = (months: number): AddonPlanFeature =>
    feature(
        'audit_logs',
        'Activity logs',
        'See who in your organization has accessed or modified entities within PostHog.',
        { limit: months, unit: 'months' }
    )
const prioritySupport = (note: string = 'Target response time 24 hours'): AddonPlanFeature =>
    feature(
        'priority_support',
        'Priority support',
        'Get help from our team faster than other customers with escalated target response times.',
        { note }
    )
const saml = feature('saml', 'SAML SSO', "Allow your organization's users to log in with SAML.")
const approvals = feature(
    'approvals',
    'Approvals',
    'Require approval workflows for changes to feature flags and other resources.'
)
const supportResponseTime = (note: string): AddonPlanFeature =>
    feature('support_response_time', 'Target support response time', 'Get help from our team!', {
        note,
        entitlement_only: true,
    })
const roleBasedAccess = feature(
    'role_based_access',
    'Role-based access control',
    'Set up custom access control rules for roles within your organization.'
)
const scim = feature('scim', 'SCIM', 'Automatically sync users and roles from your identity provider to PostHog.')
const dedicatedSupport = feature(
    'dedicated_support',
    'Dedicated account manager',
    'Work with a dedicated account manager via Slack or email to help you get the most out of PostHog.'
)
const training = feature(
    'training',
    'Ongoing training',
    'Get training from our team to help you quickly get up and running with PostHog.'
)
const termsAndConditions = feature(
    'terms_and_conditions',
    'Terms and conditions',
    'Use our standard terms, or get a custom Master Services Agreement (MSA) for enterprise plans.',
    { note: 'Custom MSA' }
)
const bespokePricing = feature('bespoke_pricing', 'Bespoke pricing', "Custom pricing to fit your company's needs.")
const invoicePayments = feature(
    'invoice_payments',
    'Payment via invoicing',
    'Pay for your PostHog subscription via invoice.'
)

const TEAMS_FEATURES: AddonPlanFeature[] = [
    projects,
    ssoEnforcement,
    twoFaEnforcement,
    prioritySupport(),
    whiteLabelling,
    advancedPermissions,
    accessControl,
    auditLogs(2),
    hipaaBaa,
    supportResponseTime('24 hours'),
    automaticProvisioning,
    dataColorThemes,
    organizationInviteSettings,
    organizationSecuritySettings,
    sessionReplayDataRetention(12),
]

const BOOST_FEATURES: AddonPlanFeature[] = [
    projects,
    ssoEnforcement,
    twoFaEnforcement,
    whiteLabelling,
    advancedPermissions,
    accessControl,
    hipaaBaa,
    automaticProvisioning,
    dataColorThemes,
    supportResponseTime('48 hours'),
    organizationInviteSettings,
    organizationSecuritySettings,
    sessionReplayDataRetention(12),
]

const SCALE_FEATURES: AddonPlanFeature[] = [
    auditLogs(2),
    prioritySupport(),
    saml,
    approvals,
    projects,
    ssoEnforcement,
    twoFaEnforcement,
    whiteLabelling,
    advancedPermissions,
    accessControl,
    hipaaBaa,
    automaticProvisioning,
    dataColorThemes,
    supportResponseTime('24 hours'),
    organizationInviteSettings,
    organizationSecuritySettings,
    sessionReplayDataRetention(12),
]

const ENTERPRISE_FEATURES: AddonPlanFeature[] = [
    dedicatedSupport,
    roleBasedAccess,
    scim,
    training,
    termsAndConditions,
    bespokePricing,
    invoicePayments,
    auditLogs(60),
    sessionReplayDataRetention(60),
    projects,
    ssoEnforcement,
    twoFaEnforcement,
    whiteLabelling,
    advancedPermissions,
    accessControl,
    hipaaBaa,
    automaticProvisioning,
    dataColorThemes,
    supportResponseTime('8 hours'),
    organizationInviteSettings,
    organizationSecuritySettings,
    prioritySupport('Target response time 8 hours'),
    saml,
    approvals,
]

type AddonSpec = {
    name: string
    description: string
    planKey: string
    price: string
    features: AddonPlanFeature[]
    legacy: boolean
}

const CATALOG: Record<AddonType, AddonSpec> = {
    [BillingPlan.Teams]: {
        name: 'Teams',
        description:
            'Priority support, unlimited projects, white labeling, HIPAA BAA, SSO enforcement, and features for collaboration with team members.',
        planKey: 'addon-20241002',
        price: '450.00',
        features: TEAMS_FEATURES,
        legacy: true,
    },
    [BillingPlan.Boost]: {
        name: 'Boost',
        description:
            'Unlimited projects, white labeling, HIPAA BAA, SSO enforcement, and features for collaboration with team members.',
        planKey: 'boost-addon-20250429',
        price: '250.00',
        features: BOOST_FEATURES,
        legacy: false,
    },
    [BillingPlan.Scale]: {
        name: 'Scale',
        description:
            'Priority support, SAML, and more features to scale your organization. Includes all features in the boost add-on features.',
        planKey: 'scale-addon-20250429',
        price: '750.00',
        features: SCALE_FEATURES,
        legacy: false,
    },
    [BillingPlan.Enterprise]: {
        name: 'Enterprise',
        description:
            'RBAC, dedicated support, training, and more. Includes all features in the scales and boost add-on features.',
        planKey: 'enterprise-addon-20241001',
        price: '2000.00',
        features: ENTERPRISE_FEATURES,
        legacy: false,
    },
}

const makePlatformAddon = (type: AddonType): BillingProductV2AddonType => {
    const spec = CATALOG[type]
    const plan: BillingPlanType = {
        plan_key: spec.planKey,
        // boost/scale/enterprise/teams aren't in the ProductKey enum yet
        product_key: type as BillingPlanType['product_key'],
        name: spec.name,
        description: spec.description,
        image_url: null,
        docs_url: spec.legacy ? 'https://posthog.com/pricing' : 'https://posthog.com/platform-addons',
        note: null,
        unit: 'month',
        flat_rate: true,
        free_allocation: null,
        features: spec.features,
        tiers: [],
        current_plan: false,
        included_if: null,
        contact_support: null,
        unit_amount_usd: spec.price,
    }
    return {
        name: spec.name,
        description: spec.description,
        price_description: null,
        image_url: null,
        icon_key: 'IconBuilding',
        docs_url: plan.docs_url ?? 'https://posthog.com/pricing',
        type,
        tiers: [],
        tiered: false,
        included_with_main_product: false,
        subscribed: false,
        inclusion_only: false,
        contact_support: null,
        unit: null,
        display_unit: null,
        display_decimals: null,
        display_divisor: null,
        unit_amount_usd: null,
        current_amount_usd: null,
        current_usage: 0,
        projected_usage: 0,
        projected_amount_usd: null,
        plans: [plan],
        features: spec.features.map(({ key, name, description }) => ({
            key,
            name,
            description,
            images: null,
            icon_key: null,
            type: null,
        })),
        trial: spec.legacy ? null : { length: 14 },
        legacy_product: spec.legacy,
        usage_key: undefined,
        usage_limit: null,
    }
}

export const defaultPlatformAddons: BillingProductV2AddonType[] = [
    makePlatformAddon(BillingPlan.Teams),
    makePlatformAddon(BillingPlan.Boost),
    makePlatformAddon(BillingPlan.Scale),
    makePlatformAddon(BillingPlan.Enterprise),
]

export type PlatformAddonScenario = 'trial-available' | 'trial-used' | 'on-scale' | 'on-legacy-teams'

const SCENARIO_SUBSCRIBED: Record<PlatformAddonScenario, AddonType | null> = {
    'trial-available': null,
    'trial-used': null,
    'on-scale': BillingPlan.Scale,
    'on-legacy-teams': BillingPlan.Teams,
}

export const makeBillingWithPlatformAddons = (
    baseBilling: BillingType,
    scenario: PlatformAddonScenario
): BillingType => {
    const subscribedType = SCENARIO_SUBSCRIBED[scenario]
    const trialEligible = scenario === 'trial-available'

    const addons = defaultPlatformAddons.map((addon) => {
        const subscribed = addon.type === subscribedType
        const price = addon.plans?.[0]?.unit_amount_usd ?? null
        return {
            ...addon,
            subscribed,
            current_amount_usd: subscribed ? price : null,
            projected_amount_usd: subscribed ? price : null,
            // trial is offered only on non-legacy, unsubscribed addons and only until the customer uses one
            trial: addon.legacy_product || subscribed || !trialEligible ? null : { length: 14 },
        }
    })

    return {
        ...baseBilling,
        products: baseBilling.products.map((product) =>
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
