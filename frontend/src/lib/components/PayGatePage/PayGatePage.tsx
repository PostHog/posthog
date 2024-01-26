import './PayGatePage.scss'

import { IconOpenSidebar } from '@posthog/icons'
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { identifierToHuman } from 'lib/utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

interface PayGatePageInterface {
    header: string | JSX.Element
    caption: string | JSX.Element
    hideUpgradeButton?: boolean
    docsLink?: string // Link to the docs of the feature, if no link is sent, it will be hidden
    featureKey: AvailableFeature
    featureName?: string
}

export function PayGatePage({
    header,
    caption,
    hideUpgradeButton,
    docsLink,
    featureKey,
    featureName,
}: PayGatePageInterface): JSX.Element {
    const { upgradeLink } = useValues(billingLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    featureName = featureName || identifierToHuman(featureKey, 'title')

    return (
        <div className="pay-gate-page">
            <h2>{header}</h2>
            <div className="pay-caption">{caption}</div>
            <div className="pay-buttons space-y-4">
                {!isCloudOrDev && <p>This feature is available on PostHog Cloud.</p>}
                {!hideUpgradeButton && (
                    <>
                        {isCloudOrDev ? (
                            <LemonButton to={upgradeLink} type="primary" data-attr={`${featureKey}-upgrade`} center>
                                Upgrade now to get {featureName}
                            </LemonButton>
                        ) : (
                            <LemonButton
                                to={urls.upgradeToPostHogCloud()}
                                type="primary"
                                data-attr={`${featureKey}-upgrade`}
                                center
                            >
                                Learn more about PostHog cloud
                            </LemonButton>
                        )}
                    </>
                )}
                {docsLink && isCloudOrDev && (
                    <LemonButton
                        type={hideUpgradeButton ? 'primary' : 'secondary'}
                        to={`${docsLink}?utm_medium=in-product&utm_campaign=${featureKey}-upgrade-learn-more`}
                        targetBlank
                        center
                        data-attr={`${featureKey}-learn-more`}
                    >
                        Learn more <IconOpenSidebar className="ml-2" />
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
