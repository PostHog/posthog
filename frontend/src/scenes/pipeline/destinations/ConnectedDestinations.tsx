import { LemonButton } from '@posthog/lemon-ui'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { HogFunctionFiltersType, PipelineStage } from '~/types'

import { HogFunctionsList } from '../hogfunctions/list/HogFunctionsList'

export type ConnectedDestinationsProps = {
    filters: HogFunctionFiltersType
}

export function ConnectedDestinations({ filters }: ConnectedDestinationsProps): JSX.Element | null {
    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    if (!hogFunctionsEnabled) {
        return null
    }

    return (
        <HogFunctionsList
            defaultFilters={{ onlyActive: true }}
            forceFilters={{ filters }}
            extraControls={
                <>
                    <LemonButton
                        type="primary"
                        size="small"
                        to={
                            urls.pipelineNodeNew(PipelineStage.Destination) +
                            `?kind=hog_function#configuration=${JSON.stringify({ filters })}`
                        }
                    >
                        New destination
                    </LemonButton>
                </>
            }
        />
    )
}
