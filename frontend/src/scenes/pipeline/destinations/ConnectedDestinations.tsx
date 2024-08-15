import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { HogFunctionFiltersType, PipelineStage } from '~/types'

import { PipelineBackend } from '../types'
import { DestinationsTable } from './Destinations'

export type ConnectedDestinationsProps = {
    filters: HogFunctionFiltersType
}

export function ConnectedDestinations({ filters }: ConnectedDestinationsProps): JSX.Element | null {
    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    if (!hogFunctionsEnabled) {
        return null
    }

    return (
        <DestinationsTable
            defaultFilters={{
                onlyActive: true,
            }}
            forceFilters={{
                kind: PipelineBackend.HogFunction,
                filters,
            }}
        />
    )
}

export function NewConnectedDestinationButton({
    filters,
    ...props
}: ConnectedDestinationsProps & LemonButtonProps): JSX.Element | null {
    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    if (!hogFunctionsEnabled) {
        return null
    }

    return (
        <LemonButton
            type="primary"
            size="small"
            to={
                urls.pipelineNodeNew(PipelineStage.Destination) +
                `?kind=hog_function#configuration=${JSON.stringify({ filters })}`
            }
            {...props}
        >
            {props.children || 'New destination'}
        </LemonButton>
    )
}
