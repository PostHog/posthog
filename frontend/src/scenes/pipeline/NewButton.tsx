import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineAppKind, PipelineAppTab } from '~/types'

type NewButtonProps = {
    kind: PipelineAppKind
}

export function NewButton({ kind }: NewButtonProps): JSX.Element {
    return (
        <LemonButton
            data-attr={`new-${kind}`}
            to={urls.pipelineApp(kind, 'new', PipelineAppTab.Configuration)}
            type="primary"
        >
            New {kind}
        </LemonButton>
    )
}
