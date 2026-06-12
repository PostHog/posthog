import { useActions } from 'kea'

import { SourceConfig } from '@posthog/query-frontend/schema/schema-general'

import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'

export type SourceIntegrationChoiceProps = IntegrationConfigureProps & {
    sourceConfig: SourceConfig
}

export function SourceIntegrationChoice({
    sourceConfig,
    integration,
    ...props
}: SourceIntegrationChoiceProps): JSX.Element {
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
