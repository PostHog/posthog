import React from 'react'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { AvailableFeature } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { IconEmojiPeople, IconLock } from '../icons'
import { LemonButton } from '../LemonButton'
import './PayGateMini.scss'
import { FEATURE_MINIMUM_PLAN, POSTHOG_CLOUD_STANDARD_PLAN } from 'lib/constants'
import { capitalizeFirstLetter } from 'lib/utils'

export interface PayGateMiniProps {
    feature: AvailableFeature.DASHBOARD_PERMISSIONING | AvailableFeature.SSO_ENFORCEMENT // TODO: Add support for other features as we go
    style?: React.CSSProperties
    children: React.ReactNode
    overrideShouldShowGate?: boolean
}

const FEATURE_SUMMARIES: Record<
    AvailableFeature.DASHBOARD_PERMISSIONING | AvailableFeature.SSO_ENFORCEMENT,
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
}

/** A sort of paywall for premium features.
 *
 * Simply shows its children when the feature is available,
 * otherwise it presents upsell UI with the call to action that's most relevant for the circumstances.
 */
export function PayGateMini({ feature, style, children, overrideShouldShowGate }: PayGateMiniProps): JSX.Element {
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

    return gateVariant ? (
        <div className="PayGateMini" style={style}>
            <div className="PayGateMini__icon">{featureSummary.icon}</div>
            <div className="PayGateMini__description">{featureSummary.description}</div>
            <div className="PayGateMini__cta">
                Upgrade to {gateVariant === 'add-card' ? 'a premium' : `the ${capitalizeFirstLetter(planRequired)}`}{' '}
                plan to gain {featureSummary.umbrella}.
            </div>
            <LemonButton
                to={gateVariant === 'add-card' ? '/organization/billing' : undefined}
                href={
                    gateVariant === 'contact-sales'
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
        <>{children}</>
    )
}
