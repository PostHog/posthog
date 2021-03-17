import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { UserType } from '~/types'
import { sceneLogic } from './sceneLogic'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureNameBenefit } = useValues(sceneLogic)
    const { hideUpgradeModal, takeToPricing } = useActions(sceneLogic)

    return (
        <Modal
            title="Unleash PostHog's Full Power"
            okText="Upgrade Now"
            cancelText="Maybe Later"
            onOk={takeToPricing}
            onCancel={hideUpgradeModal}
            visible={!!upgradeModalFeatureNameBenefit}
        >
            <p>
                <b>{upgradeModalFeatureNameBenefit && capitalizeFirstLetter(upgradeModalFeatureNameBenefit[0])}</b> is
                an advanced PostHog feature.
            </p>
            <p>{upgradeModalFeatureNameBenefit && upgradeModalFeatureNameBenefit[1]}</p>
            <p>Upgrade now and get access to this, as well as to other powerful enhancements.</p>
        </Modal>
    )
}

export function guardPremiumFeature(
    user: UserType | null,
    showUpgradeModal: (featureName: string, featureBenefit: string) => void,
    key: string,
    name: string,
    benefit: string,
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
    if (!user) {
        featureAvailable = false
    } else if (!guardOn.cloud && user.is_multi_tenancy) {
        featureAvailable = true
    } else if (!guardOn.selfHosted && !user.is_multi_tenancy) {
        featureAvailable = true
    } else {
        featureAvailable = !!user.organization?.available_features.includes(key)
    }

    if (featureAvailable) {
        featureAvailableCallback?.()
    } else {
        showUpgradeModal(name, benefit)
    }

    return !featureAvailable
}
