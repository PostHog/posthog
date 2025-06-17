import { LemonBanner, LemonTag, Link } from '@posthog/lemon-ui'

export const ResultsInsightInfoBanner = (): JSX.Element => {
    return (
        <LemonBanner type="info" className="mb-4">
            <div className="items-center inline-flex flex-wrap">
                <span>
                    Insight results may be different from exposure results due to different data processing methods. For
                    the experiment exposure, we only count events with a valid feature flag variant, and remove outliers
                    or users with <LemonTag type="danger">$multiple</LemonTag> exposures that may skew the results,
                    while insights count all the events. This could result in different breakdowns for the same
                    experiment.&nbsp;
                    <Link
                        to="https://posthog.com/docs/experiments/common-questions"
                        className="font-semibold text-primary hover:text-primary-dark"
                    >
                        Learn more in our docs
                    </Link>
                    .
                </span>
            </div>
        </LemonBanner>
    )
}
