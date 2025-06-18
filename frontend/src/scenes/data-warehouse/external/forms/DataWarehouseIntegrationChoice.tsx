import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
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
            redirectUrl={urls.pipelineNodeNew(PipelineStage.Source, { source: sourceConfig.name })}
        />
    )
}
