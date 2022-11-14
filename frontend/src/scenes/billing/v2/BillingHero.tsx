import { BlushingHog } from 'lib/components/hedgehogs'
import './BillingHero.scss'

export const BillingHero = (): JSX.Element => {
    return (
        <div className="BillingHero">
            <div className="p-4">
                <p className="text-xs uppercase my-0">How pricing works</p>
                <h1 className="ingestion-title">Get the whole hog.</h1>
                <h1 className="ingestion-title text-danger">Only pay for what you use.</h1>
                <p className="mt-2 mb-0">Product analytics, session recording, feature flags, a/b testing, and more.</p>
            </div>
            <div className="BillingHero__hog">
                <BlushingHog className="BillingHero__hog__img" />
            </div>
        </div>
    )
}
