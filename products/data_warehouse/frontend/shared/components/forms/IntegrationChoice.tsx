import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { urls } from 'scenes/urls'

import { SourceConfig } from '~/queries/schema/schema-general'

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
    const { location } = useValues(router)
    const sourceKind = sourceConfig.name.toLowerCase()

    // In onboarding the wizard is embedded in the page. A full-page OAuth redirect to the
    // standalone new-source scene would drop the user out of the onboarding flow, so when we're
    // on an onboarding route we return to the current onboarding URL with the source kind instead.
    // InlineSourceSetup reads that kind on mount and resumes the wizard (credentials are restored
    // from the state saved by beforeRedirect). Outside onboarding the standalone scene is correct.
    const isOnboarding = location.pathname.includes('/onboarding')
    let redirectUrl: string
    if (isOnboarding) {
        const params = new URLSearchParams(location.search)
        params.set('kind', sourceKind)
        redirectUrl = `${location.pathname}?${params.toString()}`
    } else {
        redirectUrl = urls.dataWarehouseSourceNew(sourceKind)
    }

    return (
        <IntegrationChoice
            {...props}
            integration={integration ?? sourceKind}
            redirectUrl={redirectUrl}
            beforeRedirect={saveFormStateBeforeRedirect}
        />
    )
}
