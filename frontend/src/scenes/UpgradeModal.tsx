import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import React from 'react'
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
