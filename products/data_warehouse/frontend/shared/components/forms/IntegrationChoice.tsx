import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import {
    IntegrationChoice,
    IntegrationConfigureProps,
} from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { getIntegrationSetup } from 'lib/components/CyclotronJob/integrations/integrationSetupRegistry'
import { useIntegrationManagementRestriction } from 'lib/integrations/integrationPermissions'
import { integrationsLogic, OAUTH_INTEGRATION_ID_PARAM } from 'lib/integrations/integrationsLogic'
import { describeOAuthCallbackError, INTEGRATION_ERROR_PARAM } from 'lib/integrations/oauthCallbackErrors'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { sourceWizardLogic } from '../../../scenes/NewSourceScene/sourceWizardLogic'

export type SourceIntegrationChoiceProps = IntegrationConfigureProps & {
    sourceConfig: SourceConfigResponseApi
}

/** The connection the OAuth callback just created, when it is one this field can use. The callback
 *  appends its id to the URL it returns to; a field that ignores it keeps whatever it held before
 *  the round-trip, which is the connection a reconnecting user just replaced. */
export function authorizedIntegrationId(
    searchParams: Record<string, any>,
    integrations: IntegrationType[] | null,
    kind: string
): number | null {
    const id = Number(searchParams[OAUTH_INTEGRATION_ID_PARAM])
    if (!Number.isInteger(id) || id <= 0) {
        return null
    }
    // Any kind's callback can land on this URL, and holding another provider's connection here
    // would only surface later as a failed schema discovery.
    return integrations?.some((integration) => integration.id === id && integration.kind === kind) ? id : null
}

export function SourceIntegrationChoice({
    sourceConfig,
    integration,
    value,
    onChange,
    ...props
}: SourceIntegrationChoiceProps): JSX.Element {
    const { saveFormStateBeforeRedirect } = useActions(sourceWizardLogic)
    const { location, searchParams } = useValues(router)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const integrationManagementRestriction = useIntegrationManagementRestriction()
    const sourceKind = sourceConfig.name.toLowerCase()
    const kind = integration ?? sourceKind

    // Members can't start an OAuth connect (see IntegrationChoice), and the only hint is a tooltip
    // on a disabled menu item. With no existing connection to pick, they have no way forward.
    const blockedFromConnecting =
        !!integrationManagementRestriction &&
        !integrationsLoading &&
        !getIntegrationSetup(kind) &&
        !integrations?.some((existing) => existing.kind === kind)

    // A failed authorization sends the user back here, where the connect button is. The callback
    // carries the reason in the URL rather than a toast, which would be gone before they retry.
    const oauthError = searchParams[INTEGRATION_ERROR_PARAM]

    const adoptedAuthorizedIntegration = useRef(false)
    useEffect(() => {
        if (adoptedAuthorizedIntegration.current || integrationsLoading) {
            return
        }
        const authorizedId = authorizedIntegrationId(searchParams, integrations, kind)
        if (authorizedId === null) {
            return
        }
        adoptedAuthorizedIntegration.current = true
        if (value !== authorizedId) {
            onChange?.(authorizedId)
        }
        // Consume the one-shot param, so remounting this field later can't override an account the
        // user picked by hand after coming back.
        const params = new URLSearchParams(location.search)
        params.delete(OAUTH_INTEGRATION_ID_PARAM)
        const query = params.toString()
        router.actions.replace(`${location.pathname}${query ? `?${query}` : ''}${location.hash}`)
    }, [integrations, integrationsLoading, searchParams, kind, value, onChange, location])

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
            {blockedFromConnecting && (
                <LemonBanner type="info">
                    Only project admins can connect a new {getIntegrationNameFromKind(kind)} account. Ask a project
                    admin to connect it, then pick it here.
                </LemonBanner>
            )}
            <IntegrationChoice
                {...props}
                value={value}
                onChange={onChange}
                integration={kind}
                redirectUrl={redirectUrl}
                beforeRedirect={saveFormStateBeforeRedirect}
            />
        </div>
    )
}
