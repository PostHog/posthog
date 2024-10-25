import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { actionEditLogic } from 'scenes/actions/actionEditLogic'
import { actionLogic } from 'scenes/actions/actionLogic'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

import { HogFunctionFiltersType } from '~/types'

export function ActionHogFunctions(): JSX.Element | null {
    const { action } = useValues(actionLogic)
    const { hasCohortFilters, actionChanged, showCohortDisablesFunctionsWarning } = useValues(
        actionEditLogic({ id: action?.id, action })
    )
    if (!action) {
        return null
    }

    const filters: HogFunctionFiltersType = {
        actions: [
            {
                id: `${action?.id}`,
                name: action?.name,
                type: 'actions',
            },
        ],
    }

    return (
        <div className="my-4 space-y-2">
            <h2 className="flex-1 subtitle">Connected destinations</h2>
            <p>Actions can be used a filters for destinations such as Slack or Webhook delivery</p>

            {showCohortDisablesFunctionsWarning ? (
                <LemonBanner type="error">Adding a cohort filter will disable all connected destinations!</LemonBanner>
            ) : null}

            <LinkedHogFunctions
                type="destination"
                filters={filters}
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
