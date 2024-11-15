import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ReactNode } from 'react'
import { urls } from 'scenes/urls'

import { PipelineStage } from '~/types'

export function overlayForNewPipelineMenu(dataAttr: string): ReactNode[] {
    return Object.entries(PipelineStage)
        .filter(([_, value]) => value != 'site-app' && value != 'legacy-source')
        .map(([key, value]) => (
            <LemonButton
                key={value}
                to={urls.pipelineNodeNew(value)}
                data-attr={dataAttr}
                data-attr-pipeline-type={value}
            >
                <div className="flex flex-col text-sm py-1">
                    <strong>{key}</strong>
                </div>
            </LemonButton>
        ))
}
