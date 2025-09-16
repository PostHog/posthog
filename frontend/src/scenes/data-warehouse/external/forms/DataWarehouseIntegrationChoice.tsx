import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

import { SourceConfig } from '~/queries/schema/schema-general'

export type DataWarehouseIntegrationChoice = IntegrationConfigureProps & {
    sourceConfig: SourceConfig
}

export function DataWarehouseIntegrationChoice({
    sourceConfig,
    integration,
    ...props
}: DataWarehouseIntegrationChoice): JSX.Element {
    return (
        <IntegrationChoice
            {...props}
            integration={integration ?? sourceConfig.name.toLowerCase()}
            redirectUrl={urls.dataWarehouseSourceNew(sourceConfig.name.toLowerCase())}
        />
    )
}
