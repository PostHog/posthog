import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

type NewButtonProps = {
    stage: PipelineStage
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}

export function NewButton({ stage, size }: NewButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr={`new-${stage}`}
            to={urls.pipelineNodeNew(stage)}
            type="primary"
            icon={<IconPlusSmall />}
            size={size}
        >
            New {stage}
        </LemonButton>
    )
}
