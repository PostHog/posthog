import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { AvailableFeatures, PreflightStatus, UserType } from '~/types'
import { sceneLogic } from './sceneLogic'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureNameAndCaption } = useValues(sceneLogic)
    const { hideUpgradeModal, takeToPricing } = useActions(sceneLogic)

    const [featureName, featureCaption] = upgradeModalFeatureNameAndCaption ?? []

    return (
        <Modal
            title="Unleash PostHog's Full Power"
            okText="Upgrade Now"
            cancelText="Maybe Later"
            onOk={takeToPricing}
            onCancel={hideUpgradeModal}
            visible={!!featureName}
        >
            <p>
                <b>{featureName && capitalizeFirstLetter(featureName)}</b> is an advanced PostHog feature.
            </p>
            {featureCaption && <p>{featureCaption}</p>}
            <p>Upgrade now and get access to this, as well as to other powerful enhancements.</p>
        </Modal>
    )
}

export function guardPremiumFeature(
    user: UserType | null,
    preflight: PreflightStatus | null,
    showUpgradeModal: (featureName: string, featureCaption: string) => void,
    key: AvailableFeatures,
    name: string,
    caption: string,
    featureAvailableCallback?: () => void,
    guardOn: {
        cloud: boolean
        selfHosted: boolean
    } = {
        cloud: true,
        selfHosted: true,
    }
): boolean {
    let featureAvailable: boolean
    if (!preflight || !user) {
        featureAvailable = false
    } else if (!guardOn.cloud && preflight.cloud) {
        featureAvailable = true
    } else if (!guardOn.selfHosted && !preflight.cloud) {
        featureAvailable = true
    } else {
        featureAvailable = !!user.organization?.available_features.includes(key)
    }

    if (featureAvailable) {
        featureAvailableCallback?.()
    } else {
        showUpgradeModal(name, caption)
    }

    return !featureAvailable
}
