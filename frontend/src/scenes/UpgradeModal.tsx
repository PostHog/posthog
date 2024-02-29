import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import posthog from 'posthog-js'

import { billingLogic } from './billing/billingLogic'
import { sceneLogic } from './sceneLogic'
import { urls } from './urls'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureNameAndCaption } = useValues(sceneLogic)
    const { hideUpgradeModal } = useActions(sceneLogic)

    const [featureName, featureCaption] = upgradeModalFeatureNameAndCaption ?? []
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing } = useValues(billingLogic)

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
                        {featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'subscribe'
                            ? 'Subscribe'
                            : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                              !billing?.has_active_subscription
                            ? 'Add credit card'
                            : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                              billing?.has_active_subscription
                            ? 'Add paid plan'
                            : 'Upgrade'}{' '}
                        now
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
            <p className="mb-0">
                {featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'subscribe'
                    ? 'Subscribe'
                    : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                      !billing?.has_active_subscription
                    ? 'Add a credit card'
                    : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                      billing?.has_active_subscription
                    ? 'Add paid plan'
                    : 'Upgrade'}{' '}
                to get access to this and other powerful enhancements.
            </p>
        </LemonModal>
    )
}
