import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'scenes/pipeline/hogfunctions/integrations/IntegrationChoice'

import { SourceConfig } from '~/types'

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
            redirectUrl={`/data-warehouse/new?kind=${sourceConfig.name.toLowerCase()}`}
        />
    )
}
