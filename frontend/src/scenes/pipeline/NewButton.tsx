import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

type NewButtonProps = {
    stage: PipelineStage
}

export function NewButton({ stage }: NewButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr={`new-${stage}`}
            to={urls.pipelineNode(stage, 'new', PipelineNodeTab.Configuration)}
            type="primary"
        >
            New {stage}
        </LemonButton>
    )
}
