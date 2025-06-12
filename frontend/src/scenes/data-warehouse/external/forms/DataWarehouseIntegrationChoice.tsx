import { IntegrationChoice, IntegrationConfigureProps } from 'scenes/hog-functions/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

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
            redirectUrl={urls.dataWarehouseSourceNew(sourceConfig.name.toLowerCase())}
        />
    )
}
