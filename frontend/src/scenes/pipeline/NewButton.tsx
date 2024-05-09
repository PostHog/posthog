import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

import { pipelineLogic } from './pipelineLogic'

type NewButtonProps = {
    stage: PipelineStage
}

export function NewButton({ stage }: NewButtonProps): JSX.Element {
    const { canEnableNewDestinations } = useValues(pipelineLogic)
    if (stage === PipelineStage.Destination && !canEnableNewDestinations) {
        return <></>
    }
    return (
        <LemonButton data-attr={`new-${stage}`} to={urls.pipelineNodeNew(stage)} type="primary">
            New {stage}
        </LemonButton>
    )
}
