import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { OrganizationType, UserType } from '~/types'
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
    organization: OrganizationType | null | undefined,
    showUpgradeModal: (featureName: string) => void,
    key: string,
    name: string,
    callback?: () => void
): boolean {
    const featureAvailable = !!organization?.available_features.includes(key)
    if (featureAvailable) callback?.()
    else showUpgradeModal(name)
    return featureAvailable
}
