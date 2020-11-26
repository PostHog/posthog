import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { UserType } from '~/types'
import { sceneLogic } from './sceneLogic'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureName } = useValues(sceneLogic)
    const { hideUpgradeModal, takeToPricing } = useActions(sceneLogic)

    return (
        <Modal
            title="Unleash PostHog's Full Power"
            okText="Upgrade Now"
            cancelText="Maybe Later"
            onOk={takeToPricing}
            onCancel={hideUpgradeModal}
            visible={!!upgradeModalFeatureName}
        >
            <b>{upgradeModalFeatureName && capitalizeFirstLetter(upgradeModalFeatureName)}</b> is an advanced PostHog
            feature. Upgrade now and get access to this, as well as to other powerful enhancements.
        </Modal>
    )
}

export function guardPremiumFeature(
    user: UserType | null,
    showUpgradeModal: (featureName: string) => void,
    key: string,
    name: string,
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
        showUpgradeModal(name)
    }

    return !featureAvailable
}
