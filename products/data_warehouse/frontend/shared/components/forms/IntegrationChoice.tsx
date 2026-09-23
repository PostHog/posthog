import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { describeOAuthCallbackError, INTEGRATION_ERROR_PARAM } from 'lib/integrations/oauthCallbackErrors'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'

export type SourceIntegrationChoiceProps = IntegrationConfigureProps & {
    sourceConfig: SourceConfigResponseApi
}

export function SourceIntegrationChoice({
    sourceConfig,
    integration,
    ...props
}: SourceIntegrationChoiceProps): JSX.Element {
    const { saveFormStateBeforeRedirect } = useActions(sourceWizardLogic)
    const { location, searchParams } = useValues(router)
    const sourceKind = sourceConfig.name.toLowerCase()

    // A failed authorization sends the user back here, where the connect button is. The callback
    // carries the reason in the URL rather than a toast, which would be gone before they retry.
    const oauthError = searchParams[INTEGRATION_ERROR_PARAM]

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
        <div className="flex flex-col gap-2">
            {oauthError && (
                <LemonBanner type="error">{describeOAuthCallbackError(String(oauthError), sourceKind)}</LemonBanner>
            )}
            <IntegrationChoice
                {...props}
                integration={integration ?? sourceKind}
                redirectUrl={redirectUrl}
                beforeRedirect={saveFormStateBeforeRedirect}
            />
        </div>
    )
}
