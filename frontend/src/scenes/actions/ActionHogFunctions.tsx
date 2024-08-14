import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { actionLogic } from 'scenes/actions/actionLogic'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'
import { PipelineBackend } from 'scenes/pipeline/types'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

export function ActionHogFunctions(): JSX.Element | null {
    const { action } = useValues(actionLogic)

    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    if (!action || !hogFunctionsEnabled) {
        return null
    }

    return (
        <div className="my-4 space-y-2">
            <div className="flex items-center gap-2">
                <h2 className="flex-1 subtitle">Connected destinations</h2>

                <LemonButton
                    type="primary"
                    size="small"
                    to={
                        urls.pipelineNodeNew(PipelineStage.Destination) +
                        `?kind=hog_function#configuration=${JSON.stringify({
                            filters: {
                                actions: [
                                    {
                                        id: `${action?.id}`,
                                        name: `${action?.name}`,
                                        type: 'actions',
                                    },
                                ],
                            },
                        })}`
                    }
                >
                    New destination
                </LemonButton>
            </div>
            <p>Actions can be used a filters for destinations such as Slack or Webhook delivery</p>

            <DestinationsTable
                defaultFilters={{
                    onlyActive: true,
                }}
                forceFilters={{
                    kind: PipelineBackend.HogFunction,
                    filters: { actions: [{ id: `${action.id}` }] },
                }}
            />
        </div>
    )
}
