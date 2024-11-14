import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ReactNode } from 'react'

export function overlayForNewPipelineMenu(dataAttr: string): ReactNode[] {
    const menuEntries = [
        { name: 'Source', url: 'pipeline/new/source' },
        { name: 'Transformation', url: 'pipeline/new/transformation' },
        { name: 'Destination', url: 'pipeline/new/destination' },
    ]

    return menuEntries.map(({ name, url }) => (
        <LemonButton key="pipelineType" to={url} data-attr={dataAttr} data-attr-pipeline-type="pipelineType">
            <div className="flex flex-col text-sm py-1">
                <strong>{name}</strong>
            </div>
        </LemonButton>
    ))
}
