import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

export function RequireEvaluationContexts(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    // Check if evaluation tags feature flag is enabled
    if (!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS]) {
        return null
    }

    const isRequiredEnabled = currentTeam?.require_evaluation_contexts || false

    const handleToggle = (enabled: boolean): void => {
        updateCurrentTeam({
            require_evaluation_contexts: enabled,
        })
    }

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <h3 className="min-w-[25rem]">Require Evaluation Contexts</h3>

                <p>
                    When enabled, all new feature flags must have at least one{' '}
                    <Link
                        to="https://posthog.com/docs/feature-flags/evaluation-contexts"
                        target="_blank"
                        disableDocsPanel
                    >
                        evaluation context
                    </Link>{' '}
                    before they can be created. This helps prevent folks from creating flags that are not properly
                    scoped to specific environments.
                </p>

                <LemonSwitch
                    data-attr="require-evaluation-contexts-switch"
                    onChange={handleToggle}
                    label="Require evaluation contexts for new flags"
                    bordered
                    checked={isRequiredEnabled}
                />
            </div>
        </div>
    )
}
