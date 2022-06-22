import { useValues } from 'kea'
import React from 'react'
import { LinkButton } from '../LinkButton'
import { userLogic } from 'scenes/userLogic'
import { identifierToHuman } from 'lib/utils'
import { IconOpenInNew } from '../icons'
import './PayGatePage.scss'
import { AvailableFeature } from '~/types'

interface PayGatePageInterface {
    header: string | JSX.Element
    caption: string | JSX.Element
    hideUpgradeButton?: boolean
    docsLink?: string // Link to the docs of the feature, if no link is sent, it will be hidden
    featureKey: AvailableFeature
}

export function PayGatePage({
    header,
    caption,
    hideUpgradeButton,
    docsLink,
    featureKey,
}: PayGatePageInterface): JSX.Element {
    const { upgradeLink } = useValues(userLogic)
    const featureName = identifierToHuman(featureKey, 'title')

    return (
        <div className="pay-gate-page">
            <h2>{header}</h2>
            <div className="pay-caption">{caption}</div>
            <div className="pay-buttons">
                {!hideUpgradeButton && (
                    <LinkButton
                        to={upgradeLink}
                        type="primary"
                        data-attr={`${featureKey}-upgrade`}
                        className="LemonLinkButton"
                    >
                        Upgrade now to get {featureName}
                    </LinkButton>
                )}
                {docsLink && (
                    <LinkButton
                        type={hideUpgradeButton ? 'primary' : undefined}
                        to={`${docsLink}?utm_medium=in-product&utm_campaign=${featureKey}-upgrade-learn-more`}
                        target="_blank"
                        data-attr={`${featureKey}-learn-more`}
                        className="LemonLinkButton"
                    >
                        Learn more about {featureName} <IconOpenInNew style={{ marginLeft: 8 }} />
                    </LinkButton>
                )}
            </div>
        </div>
    )
}
