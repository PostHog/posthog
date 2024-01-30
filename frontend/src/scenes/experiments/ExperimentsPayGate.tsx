import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'

import { AvailableFeature } from '~/types'

export function ExperimentsPayGate(): JSX.Element {
    return (
        <PayGatePage
            featureKey={AvailableFeature.EXPERIMENTATION}
            header={
                <>
                    Test changes with <span className="highlight">statistical significance</span>
                </>
            }
            caption="A/B tests, multivariate tests, and robust targeting & exclusion rules. Analyze usage with product analytics and session replay."
            docsLink="https://posthog.com/docs/user-guides/experimentation"
        />
    )
}
