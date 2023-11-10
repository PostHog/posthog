import { BlushingHog } from 'lib/components/hedgehogs'
import './BillingHero.scss'

export const BillingHero = (): JSX.Element => {
    return (
        <div className="BillingHero">
            <div className="p-4">
                <p className="text-xs uppercase my-0">How pricing works</p>
                <h1 className="ingestion-title">Get the whole hog.</h1>
                <h1 className="ingestion-title text-danger">Only pay for what you use.</h1>
                <p className="mt-2 mb-0">
                    Add your credit card details to get access to premium product and platform features. Set billing
                    limits as low as $0 to control spend.
                </p>
            </div>
            <div className="BillingHero__hog">
                <BlushingHog className="BillingHero__hog__img" />
            </div>
        </div>
    )
}
