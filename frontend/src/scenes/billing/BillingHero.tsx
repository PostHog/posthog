import './BillingHero.scss'

import { BlushingHog } from 'lib/components/hedgehogs'
import useResizeObserver from 'use-resize-observer'

export const BillingHero = (): JSX.Element => {
    const { width, ref: billingHeroRef } = useResizeObserver()

    return (
        <div className="BillingHero" ref={billingHeroRef}>
            <div className="p-4">
                <p className="text-xs uppercase my-0">How pricing works</p>
                <h1 className="ingestion-title">Get the whole hog.</h1>
                <h1 className="ingestion-title text-danger">Only pay for what you use.</h1>
                <p className="mt-2 mb-0">
                    Upgrade to get access to premium product and platform features. Set billing limits as low as $0 to
                    control spend.
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
