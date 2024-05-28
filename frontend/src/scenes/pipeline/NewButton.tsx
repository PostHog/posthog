import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

import { pipelineAccessLogic } from './pipelineAccessLogic'

type NewButtonProps = {
    stage: PipelineStage
}

export function NewButton({ stage }: NewButtonProps): JSX.Element {
    const { canEnableNewDestinations } = useValues(pipelineAccessLogic)
    if (stage === PipelineStage.ImportApp || (stage === PipelineStage.Destination && !canEnableNewDestinations)) {
        return <></>
    }
    return (
        <LemonButton
            data-attr={`new-${stage}`}
            to={stage === PipelineStage.DataImport ? urls.pipelineNodeDataWarehouseNew() : urls.pipelineNodeNew(stage)}
            type="primary"
            icon={<IconPlusSmall />}
        >
            New {stage}
        </LemonButton>
    )
}
