import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { evalSuggestionsSettingsLogic } from './evalSuggestionsSettingsLogic'

export function EvalSuggestionsSettings(): JSX.Element {
    const { suggestionSettings, suggestionSettingsLoading } = useValues(evalSuggestionsSettingsLogic)
    const { setSuggestionsEnabled } = useActions(evalSuggestionsSettingsLogic)

    return (
        <LemonSwitch
            bordered
            label="Show suggested evals"
            checked={suggestionSettings?.enabled ?? false}
            loading={suggestionSettingsLoading}
            disabledReason={
                suggestionSettings
                    ? undefined
                    : suggestionSettingsLoading
                      ? 'Loading the setting'
                      : "Couldn't load the setting. Refresh the page."
            }
            onChange={(enabled) => setSuggestionsEnabled(enabled)}
            data-attr="eval-suggestions-setting"
        />
    )
}
