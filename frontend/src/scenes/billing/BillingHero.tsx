import './BillingHero.scss'

import { useValues } from 'kea'
import { BlushingHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import useResizeObserver from 'use-resize-observer'

import { billingLogic } from './billingLogic'

export const BillingHero = (): JSX.Element => {
    const { width, ref: billingHeroRef } = useResizeObserver()
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing } = useValues(billingLogic)

    return (
        <div className="BillingHero" ref={billingHeroRef}>
            <div className="p-4">
                <p className="text-xs uppercase my-0">How pricing works</p>
                <h1 className="ingestion-title">Get the whole hog.</h1>
                <h1 className="ingestion-title text-danger">Only pay for what you use.</h1>
                <p className="mt-2 mb-0">
                    {featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'subscribe'
                        ? 'Subscribe'
                        : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                          !billing?.has_active_subscription
                        ? 'Add your credit card'
                        : featureFlags[FEATURE_FLAGS.BILLING_UPGRADE_LANGUAGE] === 'credit_card' &&
                          billing?.has_active_subscription
                        ? 'Add the paid plan'
                        : 'Upgrade'}{' '}
                    to get access to premium product and platform features. Set billing limits as low as $0 to control
                    spend.
                </p>
            </div>
            {width && width > 500 && (
                <div className="BillingHero__hog shrink-0">
                    <BlushingHog className="BillingHero__hog__img" />
                </div>
            )}
        </div>
    )
}
