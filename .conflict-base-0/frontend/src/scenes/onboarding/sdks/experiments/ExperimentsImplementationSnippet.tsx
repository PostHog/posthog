import { OPTIONS } from 'scenes/experiments/ExperimentImplementationDetails'

import { SDKKey } from '~/types'

export const ExperimentsImplementationSnippet = ({ sdkKey }: { sdkKey: SDKKey }): JSX.Element => {
    const option = OPTIONS.find((option) => option.key === sdkKey)
    const Snippet = option?.Snippet || (() => null)
    return (
        <>
            <h3>Basic implementation</h3>
            <p>
                Experiments run on top of our feature flags. You can define which version of your code runs based on the
                return value of the feature flag.
            </p>
            <Snippet flagKey="your-experiment-feature-flag" variant="test" />
            <h3>Running experiments</h3>
            <p>
                Once you've implemented the feature flag in your code, you'll enable it for a target audience by
                creating a new experiment in the PostHog dashboard.
            </p>
        </>
    )
}
