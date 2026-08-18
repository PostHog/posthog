import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonSnack, LemonTextArea } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { personalAPIKeysLogic } from './personalAPIKeysLogic'

/** Primary scope input for the AI scope picker experiment: describe the job, get scopes back. */
export function ScopeDescriptionField(): JSX.Element {
    const { scopeDescription, scopeSuggestion, scopeSuggestionLoading } = useValues(personalAPIKeysLogic)
    const { setScopeDescription, suggestScopes } = useActions(personalAPIKeysLogic)

    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>What will this key do?</LemonLabel>
            <LemonTextArea
                value={scopeDescription}
                onChange={setScopeDescription}
                onPressCmdEnter={() => suggestScopes()}
                placeholder='For example "read insights and dashboards for a weekly report", or "create and update feature flags from CI"'
                maxLength={1000}
                minRows={2}
                data-attr="personal-api-key-scope-description"
            />
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconSparkles />}
                    loading={scopeSuggestionLoading}
                    disabledReason={!scopeDescription.trim() ? 'Describe what the key will do first' : undefined}
                    onClick={() => suggestScopes()}
                    data-attr="personal-api-key-suggest-scopes"
                >
                    Suggest scopes
                </LemonButton>
            </div>
            {!scopeSuggestionLoading && scopeSuggestion ? (
                scopeSuggestion.scopes.length > 0 ? (
                    <LemonBanner type="info">
                        <p className="mb-2">
                            {scopeSuggestion.summary ||
                                'Selected the scopes below. Open the scope list to check or change them.'}
                        </p>
                        <span className="flex flex-wrap gap-1">
                            {scopeSuggestion.scopes.map((scope) => (
                                <LemonSnack key={scope}>{scope}</LemonSnack>
                            ))}
                        </span>
                    </LemonBanner>
                ) : (
                    <LemonBanner type="warning">
                        {scopeSuggestion.summary ||
                            "Couldn't tell which scopes that needs. Add more detail, or open the scope list to pick them yourself."}
                    </LemonBanner>
                )
            ) : null}
        </div>
    )
}
