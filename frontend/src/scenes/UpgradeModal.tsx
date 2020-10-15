import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
import { UserType } from '~/types'
import { sceneLogic } from './sceneLogic'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureName } = useValues(sceneLogic)
    const { hideUpgradeModal } = useActions(sceneLogic)

    return (
        <Modal
            title="Unleash PostHog's Full Power"
            okText="Upgrade Now"
            cancelText="Maybe Later"
            onOk={() => {
                window.open('mailto:hey@posthog.com?subject=Upgrading PostHog')
                hideUpgradeModal()
            }}
            onCancel={hideUpgradeModal}
            visible={!!upgradeModalFeatureName}
        >
            Oops! <b>{upgradeModalFeatureName && capitalizeFirstLetter(upgradeModalFeatureName)}</b>{' '}
            {upgradeModalFeatureName && upgradeModalFeatureName[upgradeModalFeatureName.length - 1] === 's'
                ? 'are'
                : 'is'}{' '}
            an advanced PostHog feature.
            <br />
            Upgrade to a premium plan to gain access to it, as well as to other powerful enhancements.
        </Modal>
    )
}

export function guardPremiumFeature(
    user: UserType | null,
    showUpgradeModal: (featureName: string) => void,
    key: string,
    name: string,
    callback?: () => void
): boolean {
    const featureAvailable = !!user?.available_features.includes(key)
    if (featureAvailable) callback?.()
    else showUpgradeModal(name)
    return featureAvailable
}
