import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { actionLogic } from 'scenes/actions/actionLogic'
import { HogFunctionIcon } from 'scenes/pipeline/hogfunctions/HogFunctionIcon'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

export function ActionHogFunctions(): JSX.Element | null {
    const { action, matchingHogFunctions } = useValues(actionLogic)
    const { loadMatchingHogFunctions } = useActions(actionLogic)

    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    useEffect(() => {
        loadMatchingHogFunctions()
    }, [action])

    if (!matchingHogFunctions?.length && !hogFunctionsEnabled) {
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

            {matchingHogFunctions?.map((hogFunction) => (
                <div key={hogFunction.id} className="flex items-center gap-2 border rounded bg-bg-light p-2">
                    <HogFunctionIcon src={hogFunction.icon_url} size="small" />
                    <LemonTableLink
                        title={hogFunction.name}
                        to={urls.pipelineNode(
                            PipelineStage.Destination,
                            `hog-${hogFunction.id}`,
                            PipelineNodeTab.Configuration
                        )}
                    />
                    <span className="flex-1" />

                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.pipelineNode(
                            PipelineStage.Destination,
                            `hog-${hogFunction.id}`,
                            PipelineNodeTab.Configuration
                        )}
                    >
                        Configure
                    </LemonButton>
                </div>
            )) ?? <p>No destinations connected to this action</p>}
        </div>
    )
}
