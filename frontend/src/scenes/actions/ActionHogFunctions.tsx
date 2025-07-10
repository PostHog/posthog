import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { actionEditLogic } from 'scenes/actions/actionEditLogic'
import { actionLogic } from 'scenes/actions/actionLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

export function ActionHogFunctions(): JSX.Element | null {
    const { action } = useValues(actionLogic)
    const { hasCohortFilters, actionChanged, showCohortDisablesFunctionsWarning } = useValues(
        actionEditLogic({ id: action?.id, action })
    )
    if (!action) {
        return null
    }

    return (
        <div className="deprecated-space-y-2 my-4">
            <h2 className="subtitle flex-1">Connected destinations</h2>
            <p>Actions can be used a filters for destinations such as Slack or Webhook delivery</p>

            {showCohortDisablesFunctionsWarning ? (
                <LemonBanner type="error">Adding a cohort filter will disable all connected destinations!</LemonBanner>
            ) : null}

            <LinkedHogFunctions
                type="destination"
                forceFilterGroups={[
                    {
                        actions: [
                            {
                                id: `${action.id}`,
                                name: action.name,
                                type: 'actions',
                            },
                        ],
                    },
                ]}
                newDisabledReason={
                    hasCohortFilters
                        ? "Action with cohort filters can't be used in realtime destinations"
                        : actionChanged
                          ? 'Please first save the action to create a destination'
                          : undefined
                }
            />
        </div>
    )
}
