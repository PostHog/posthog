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
    redirectUrl: redirectUrlOverride,
    ...props
}: SourceIntegrationChoiceProps): JSX.Element {
    const { saveFormStateBeforeRedirect } = useActions(sourceWizardLogic)
    const { location, searchParams } = useValues(router)
    const sourceKind = sourceConfig.name.toLowerCase()

    // A failed authorization sends the user back here, where the connect button is. The callback
    // carries the reason in the URL rather than a toast, which would be gone before they retry.
    const oauthError = searchParams[INTEGRATION_ERROR_PARAM]

    // A host that embeds the wizard in its own page says where the OAuth flow returns to, because a
    // full-page redirect to the standalone new-source scene drops the user out of that page.
    // Onboarding is that same case for the one route we can recognize here: it returns to the
    // current onboarding URL with the source kind, which InlineSourceSetup reads on mount to resume
    // the wizard (credentials are restored from the state saved by beforeRedirect). With no host
    // page to return to, the standalone scene is correct.
    const isOnboarding = location.pathname.includes('/onboarding')
    let redirectUrl: string
    if (redirectUrlOverride) {
        redirectUrl = redirectUrlOverride
    } else if (isOnboarding) {
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
