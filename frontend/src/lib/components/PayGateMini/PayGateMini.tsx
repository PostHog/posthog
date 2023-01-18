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

export interface PayGateMiniProps {
    feature: PayGateSupportedFeatures
    children: React.ReactNode
    overrideShouldShowGate?: boolean
    className?: string
}

const FEATURE_SUMMARIES: Record<
    PayGateSupportedFeatures,
    {
        icon: React.ReactElement
        description: string
        umbrella: string
    }
> = {
    [AvailableFeature.DASHBOARD_PERMISSIONING]: {
        icon: <IconEmojiPeople />,
        description:
            'Share insights, collaborate on dashboards, manage permissions, and make decisions with your team.',
        umbrella: 'advanced permissioning',
    },
    [AvailableFeature.SSO_ENFORCEMENT]: {
        icon: <IconLock />,
        description:
            'Enable SAML single sign-on, enforce login with SSO, automatic user provisioning, and advanced authentication controls.',
        umbrella: 'advanced authentication',
    },
    [AvailableFeature.DASHBOARD_COLLABORATION]: {
        icon: <IconPremium />,
        description:
            'Make sense of insights your team has learned with the help of tags, descriptions, and text cards.',
        umbrella: 'advanced collaboration',
    },
    [AvailableFeature.ROLE_BASED_ACCESS]: {
        icon: <IconPremium />,
        description: 'Create custom roles to give you precise access control for your organization.',
        umbrella: 'advanced permissioning',
    },
    [AvailableFeature.CORRELATION_ANALYSIS]: {
        icon: <IconLightBulb />,
        description: 'See what events and properties are correlated with conversion or drop-off.',
        umbrella: 'correlation analysis',
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
            <div className="PayGateMini__icon">{featureSummary.icon}</div>
            <div className="PayGateMini__description">{featureSummary.description}</div>
            <div className="PayGateMini__cta">
                Upgrade to {gateVariant === 'add-card' ? 'a premium' : `the ${capitalizeFirstLetter(planRequired)}`}{' '}
                plan to gain {featureSummary.umbrella}.
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
