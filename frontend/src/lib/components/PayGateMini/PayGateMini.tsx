import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { AvailableFeature } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { IconEmojiPeople, IconLightBulb, IconLock, IconPremium } from '../icons'
import { LemonButton } from '../LemonButton'
import './PayGateMini.scss'
import { FEATURE_MINIMUM_PLAN, POSTHOG_CLOUD_STANDARD_PLAN } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'
import clsx from 'clsx'

type PayGateSupportedFeatures =
    | AvailableFeature.DASHBOARD_PERMISSIONING
    | AvailableFeature.SSO_ENFORCEMENT
    | AvailableFeature.DASHBOARD_COLLABORATION
    | AvailableFeature.ROLE_BASED_ACCESS
    | AvailableFeature.CORRELATION_ANALYSIS
    | AvailableFeature.PATHS_ADVANCED

export interface PayGateMiniProps {
    feature: PayGateSupportedFeatures
    children: React.ReactNode
    overrideShouldShowGate?: boolean
    className?: string
}

const FEATURE_SUMMARIES: Record<
    PayGateSupportedFeatures,
    {
        /** IconPremium is the default one, but choose a more relevant one when possible. */
        icon?: React.ReactElement
        description: string
        umbrella: string
        docsHref?: string
    }
> = {
    [AvailableFeature.DASHBOARD_PERMISSIONING]: {
        icon: <IconEmojiPeople />,
        description: 'Control access to this dashboard with dashboard permissions.',
        umbrella: 'team-oriented permissioning',
    },
    [AvailableFeature.SSO_ENFORCEMENT]: {
        icon: <IconLock />,
        description: 'Use SAML single sign-on, enforce login with SSO, enable automatic user provisioning.',
        umbrella: 'organization-level authentication',
        docsHref: 'https://posthog.com/manual/sso',
    },
    [AvailableFeature.DASHBOARD_COLLABORATION]: {
        description:
            'Make sense of insights your team has learned with the help of tags, descriptions, and text cards.',
        umbrella: 'collaboration features',
        docsHref: 'https://posthog.com/docs/user-guides/dashboards#tagging-a-dashboard',
    },
    [AvailableFeature.ROLE_BASED_ACCESS]: {
        description: 'Create and manage custom roles for granular access control within your organization.',
        umbrella: 'team-oriented permissioning',
        docsHref: 'https://posthog.com/manual/role-based-access',
    },
    [AvailableFeature.CORRELATION_ANALYSIS]: {
        icon: <IconLightBulb />,
        description:
            'Correlation Analysis reveals which events and properties go hand in hand with conversion or drop-off.',
        umbrella: 'advanced analysis capabilities',
        docsHref: 'https://posthog.com/manual/correlation',
    },
    [AvailableFeature.PATHS_ADVANCED]: {
        description:
            'Tune path analysis with wildcards, path cleaning rules, or custom end points, and quickly jump from a path to its funnel.',
        umbrella: 'advanced analysis capabilities',
        docsHref: 'https://posthog.com/manual/paths',
    },
}

/** A sort of paywall for premium features.
 *
 * Simply shows its children when the feature is available,
 * otherwise it presents upsell UI with the call to action that's most relevant for the circumstances.
 */
export function PayGateMini({
    feature,
    className,
    children,
    overrideShouldShowGate,
}: PayGateMiniProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const featureSummary = FEATURE_SUMMARIES[feature]
    const planRequired = FEATURE_MINIMUM_PLAN[feature]
    let gateVariant: 'add-card' | 'contact-sales' | 'check-licensing' | null = null
    if (!overrideShouldShowGate && !hasAvailableFeature(feature)) {
        if (preflight?.cloud) {
            if (planRequired === POSTHOG_CLOUD_STANDARD_PLAN) {
                gateVariant = 'add-card'
            } else {
                gateVariant = 'contact-sales'
            }
        } else {
            gateVariant = 'check-licensing'
        }
    }

    if (gateVariant && preflight?.instance_preferences?.disable_paid_fs) {
        return null // Don't show anything if paid features are explicitly disabled
    }

    return gateVariant ? (
        <div className={clsx('PayGateMini', className)}>
            <div className="PayGateMini__icon">{featureSummary.icon || <IconPremium />}</div>
            <div className="PayGateMini__description">{featureSummary.description}</div>
            <div className="PayGateMini__cta">
                Upgrade to {gateVariant === 'add-card' ? 'a premium' : `the ${capitalizeFirstLetter(planRequired)}`}{' '}
                plan to gain {featureSummary.umbrella}.
                {featureSummary.docsHref && (
                    <>
                        {' '}
                        <a href={featureSummary.docsHref} target="_blank" rel="noopener noreferrer">
                            Learn more in PostHog Docs.
                        </a>
                    </>
                )}
            </div>
            <LemonButton
                to={
                    gateVariant === 'add-card'
                        ? '/organization/billing'
                        : gateVariant === 'contact-sales'
                        ? `mailto:sales@posthog.com?subject=Inquiring about ${featureSummary.umbrella}`
                        : gateVariant === 'check-licensing'
                        ? 'https://posthog.com/pricing'
                        : undefined
                }
                type="secondary"
                fullWidth
                center
            >
                {gateVariant === 'add-card'
                    ? 'Upgrade now'
                    : gateVariant === 'contact-sales'
                    ? 'Contact sales'
                    : 'Explore license options'}
            </LemonButton>
        </div>
    ) : (
        <div className={className}>{children}</div>
    )
}
