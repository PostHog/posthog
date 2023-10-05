import { OPTIONS } from 'scenes/feature-flags/FeatureFlagCodeOptions'
import { CodeInstructions } from 'scenes/feature-flags/FeatureFlagInstructions'
import { SDKKey } from '~/types'

export const FlagImplementationSnippet = ({ sdkKey }: { sdkKey: SDKKey }): JSX.Element => {
    return (
        <>
            <h3>Basic implementation</h3>
            <CodeInstructions
                options={OPTIONS}
                selectedLanguage={sdkKey}
                showAdvancedOptions={false}
                showFooter={false}
            />
        </>
    )
}
