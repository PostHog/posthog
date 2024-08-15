import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { actionLogic } from 'scenes/actions/actionLogic'
import {
    ConnectedDestinations,
    NewConnectedDestinationButton,
} from 'scenes/pipeline/destinations/ConnectedDestinations'

import { HogFunctionFiltersType } from '~/types'

export function ActionHogFunctions(): JSX.Element | null {
    const { action } = useValues(actionLogic)
    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    if (!action || !hogFunctionsEnabled) {
        return null
    }

    const filters: HogFunctionFiltersType = {
        actions: [
            {
                id: `${action?.id}`,
                type: 'actions',
            },
        ],
    }

    return (
        <div className="my-4 space-y-2">
            <div className="flex items-center gap-2">
                <h2 className="flex-1 subtitle">Connected destinations</h2>

                <NewConnectedDestinationButton filters={filters} />
            </div>
            <p>Actions can be used a filters for destinations such as Slack or Webhook delivery</p>

            <ConnectedDestinations filters={filters} />
        </div>
    )
}
