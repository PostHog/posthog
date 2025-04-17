import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'scenes/pipeline/hogfunctions/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

import { PipelineStage, SourceConfig } from '~/types'

export type DataWarehouseIntegrationChoice = IntegrationConfigureProps & {
    sourceConfig: SourceConfig
}

export function DataWarehouseIntegrationChoice({
    sourceConfig,
    ...props
}: DataWarehouseIntegrationChoice): JSX.Element {
    return (
        <IntegrationChoice
            {...props}
            integration={sourceConfig.name.toLowerCase()}
            redirectUrl={urls.pipelineNodeNew(PipelineStage.Source, { kind: sourceConfig.name.toLowerCase() })}
        />
    )
}
