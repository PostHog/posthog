import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

type NewButtonProps = {
    stage: PipelineStage
}

export function NewButton({ stage }: NewButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr={`new-${stage}`}
            to={urls.pipelineNodeNew(stage)}
            type="primary"
            icon={<IconPlusSmall />}
        >
            New {stage}
        </LemonButton>
    )
}
