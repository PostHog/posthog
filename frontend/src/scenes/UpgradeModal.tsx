import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import { posthog } from 'posthog-js'

import { sceneLogic } from './sceneLogic'
import { urls } from './urls'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureNameAndCaption } = useValues(sceneLogic)
    const { hideUpgradeModal } = useActions(sceneLogic)

    const [featureName, featureCaption] = upgradeModalFeatureNameAndCaption ?? []

    return (
        <LemonModal
            title="Unleash PostHog's full power"
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideUpgradeModal}>
                        Maybe later
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={urls.organizationBilling()}
                        onClick={() => {
                            hideUpgradeModal()
                            posthog.capture('upgrade modal pricing interaction')
                        }}
                    >
                        Upgrade now
                    </LemonButton>
                </>
            }
            onClose={hideUpgradeModal}
            isOpen={!!featureName}
        >
            <p>
                <b>{featureName && capitalizeFirstLetter(featureName)}</b> is an advanced PostHog feature.
            </p>
            {featureCaption && <p>{featureCaption}</p>}
            <p className="mb-0">Upgrade and get access to this, as well as to other powerful enhancements.</p>
        </LemonModal>
    )
}
