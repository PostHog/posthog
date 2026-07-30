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

// In onboarding the wizard is embedded in the page. A full-page OAuth redirect to the standalone
// new-source scene would drop the user out of the onboarding flow, so when we're on an onboarding
// route we return to the current onboarding URL with the source kind instead. InlineSourceSetup
// reads that kind on mount and resumes the wizard (credentials are restored from the state saved
// by beforeRedirect). Outside onboarding the standalone scene is correct.
//
// Either way the existing query string rides along: product-embedded entry points such as
// marketing analytics pass returnUrl/returnLabel so the wizard can offer a way back, and rebuilding
// the URL from the source kind alone strands the user in a context-free wizard after OAuth.
export function getSourceOAuthRedirectUrl(pathname: string, search: string, sourceKind: string): string {
    const params = new URLSearchParams(search)
    params.set('kind', sourceKind)
    const basePath = pathname.includes('/onboarding') ? pathname : urls.dataWarehouseSourceNew()
    return `${basePath}?${params.toString()}`
}

export function SourceIntegrationChoice({
    sourceConfig,
    integration,
    ...props
}: SourceIntegrationChoiceProps): JSX.Element {
    const { saveFormStateBeforeRedirect } = useActions(sourceWizardLogic)
    const { location } = useValues(router)
    const sourceKind = sourceConfig.name.toLowerCase()
    const redirectUrl = getSourceOAuthRedirectUrl(location.pathname, location.search, sourceKind)

    return (
        <IntegrationChoice
            {...props}
            integration={integration ?? sourceKind}
            redirectUrl={redirectUrl}
            beforeRedirect={saveFormStateBeforeRedirect}
        />
    )
}
