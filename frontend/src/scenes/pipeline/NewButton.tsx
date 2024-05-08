import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

import { pipelineLogic } from './pipelineLogic'

type NewButtonProps = {
    stage: PipelineStage | undefined
}

export function NewButton({ stage }: NewButtonProps): JSX.Element {
    const { notAllowedReasonByStageAndOperationType } = useValues(pipelineLogic)

    if (!stage || notAllowedReasonByStageAndOperationType[stage]['new_or_enable']) {
        return <></>
    }
    return (
        <LemonButton data-attr={`new-${stage}`} to={urls.pipelineNodeNew(stage)} type="primary">
            New {stage}
        </LemonButton>
    )
}
