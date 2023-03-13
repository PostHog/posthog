import { useValues } from 'kea'
import { identifierToHuman } from 'lib/utils'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import './PayGatePage.scss'
import { AvailableFeature } from '~/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { billingLogic } from 'scenes/billing/billingLogic'

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
    featureName = featureName || identifierToHuman(featureKey, 'title')

    return (
        <div className="pay-gate-page">
            <h2>{header}</h2>
            <div className="pay-caption">{caption}</div>
            <div className="pay-buttons space-y-4">
                {!hideUpgradeButton && (
                    <LemonButton to={upgradeLink} type="primary" data-attr={`${featureKey}-upgrade`} center>
                        Upgrade now to get {featureName}
                    </LemonButton>
                )}
                {docsLink && (
                    <LemonButton
                        type={hideUpgradeButton ? 'primary' : 'secondary'}
                        to={`${docsLink}?utm_medium=in-product&utm_campaign=${featureKey}-upgrade-learn-more`}
                        targetBlank
                        center
                        data-attr={`${featureKey}-learn-more`}
                    >
                        Learn more about {featureName} <IconOpenInNew style={{ marginLeft: 8 }} />
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
