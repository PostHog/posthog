import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { actionLogic } from 'scenes/actions/actionLogic'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'

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
                name: action?.name,
                type: 'actions',
            },
        ],
    }

    return (
        <div className="my-4 space-y-2">
            <h2 className="flex-1 subtitle">Connected destinations</h2>
            <p>Actions can be used a filters for destinations such as Slack or Webhook delivery</p>

            <LinkedHogFunctions filters={filters} />
        </div>
    )
}
