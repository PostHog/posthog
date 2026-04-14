import { useActions } from 'kea'

import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

import { SourceConfig } from '~/queries/schema/schema-general'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'

export type IntegrationChoiceProps = IntegrationConfigureProps & {
    sourceConfig: SourceConfig
}

export function IntegrationChoice({ sourceConfig, integration, ...props }: IntegrationChoiceProps): JSX.Element {
    const { saveFormStateBeforeRedirect } = useActions(sourceWizardLogic)
    const sourceKind = sourceConfig.name.toLowerCase()
    return (
        <IntegrationChoice
            {...props}
            integration={integration ?? sourceKind}
            redirectUrl={urls.dataWarehouseSourceNew(sourceKind)}
            beforeRedirect={saveFormStateBeforeRedirect}
        />
    )
}
