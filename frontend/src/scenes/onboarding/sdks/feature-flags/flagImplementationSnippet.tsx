import { OPTIONS } from 'scenes/feature-flags/FeatureFlagCodeOptions'
import { CodeInstructions } from 'scenes/feature-flags/FeatureFlagInstructions'

import { SDKKey } from '~/types'

export const FlagImplementationSnippet = ({ sdkKey }: { sdkKey: SDKKey }): JSX.Element => {
    return (
        <>
            <h3>Basic flag implementation</h3>
            <CodeInstructions
                options={OPTIONS}
                selectedLanguage={sdkKey}
                showAdvancedOptions={false}
                showFooter={false}
            />
            <h3>Running experiments</h3>
            <p>
                Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an
                experiment by creating a new experiment in the PostHog dashboard.
            </p>
        </>
    )
}
