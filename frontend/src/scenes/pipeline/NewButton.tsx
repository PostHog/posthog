import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs } from '~/types'

import { singularName } from './pipelineLogic'

type NewButtonProps = {
    tab: PipelineTabs
}

export function NewButton({ tab }: NewButtonProps): JSX.Element {
    const singular = singularName(tab)
    return (
        <LemonButton
            data-attr={`new-${singular}`}
            to={urls.pipelineApp(tab, 'new', PipelineAppTabs.Configuration)}
            type="primary"
        >
            New {singular}
        </LemonButton>
    )
}
