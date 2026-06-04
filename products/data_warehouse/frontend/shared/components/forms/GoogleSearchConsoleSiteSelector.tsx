import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { googleSearchConsoleIntegrationLogic } from 'lib/integrations/googleSearchConsoleIntegrationLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

const SITE_URL_PLACEHOLDER = 'https://example.com/ or sc-domain:example.com'

/**
 * Renders the Search Console `site_url` field as a free-text input with a popover
 * of the connected integration's verified properties for autocomplete-style picking.
 *
 * Falls back to a plain text input before the user picks an OAuth account (or when
 * the form's stored integration ID points at a stale integration), so the field
 * stays usable while the integration choice above is being fixed.
 *
 * Works in both contexts that render this field:
 *   - The new-source wizard (`sourceWizardLogic`, form key `sourceConnectionDetails`)
 *   - The existing-source Config tab (`sourceSettingsLogic`, form key `sourceConfig`)
 *
 * We read the OAuth integration ID via `FormContext` from kea-forms instead of
 * binding directly to a specific logic, so this stays decoupled from which scene
 * renders it.
 */
export function GoogleSearchConsoleSiteSelector(): JSX.Element {
    const integrationId = useFormIntegrationId()
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const integrationIsValid = useMemo(() => {
        if (!integrationId || integrationsLoading || !integrations) {
            return false
        }
        return integrations.some(
            (integration) => integration.id === integrationId && integration.kind === 'google-search-console'
        )
    }, [integrationId, integrations, integrationsLoading])

    if (integrationIsValid && integrationId) {
        return <GoogleSearchConsoleSiteFieldWithSuggestions integrationId={integrationId} />
    }

    return (
        <LemonField name="site_url" label="Property URL">
            {({ value, onChange }) => (
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="site_url"
                    placeholder={SITE_URL_PLACEHOLDER}
                    type="text"
                    value={value || ''}
                    onChange={onChange}
                />
            )}
        </LemonField>
    )
}

function useFormIntegrationId(): number | undefined {
    const formContext = useContext(FormContext)
    const values = useValues((formContext.logic ?? null) as any) as Record<string, any> | null
    if (!formContext.logic || !values) {
        return undefined
    }
    // Coerce to number — when the form is hydrated from a saved source's `job_inputs`
    // the integration ID arrives as a string from JSONB. Without the cast, downstream
    // `integration.id === id` lookups in `integrationsLogic` silently miss the match.
    const raw = values[formContext.formKey]?.payload?.google_search_console_integration_id
    const id = raw === undefined || raw === null || raw === '' ? undefined : Number(raw)
    return id && Number.isFinite(id) ? id : undefined
}

function GoogleSearchConsoleSiteFieldWithSuggestions({ integrationId }: { integrationId: number }): JSX.Element {
    const { sites, sitesLoading } = useValues(googleSearchConsoleIntegrationLogic({ id: integrationId }))
    const { loadSites } = useActions(googleSearchConsoleIntegrationLogic({ id: integrationId }))

    useEffect(() => {
        loadSites()
    }, [loadSites])

    const siteUrls = useMemo(() => sites.map((site) => site.siteUrl), [sites])

    return (
        <LemonField name="site_url" label="Property URL">
            {({ value, onChange }) => {
                const savedValueMissing = !!value && !sitesLoading && sites.length > 0 && !siteUrls.includes(value)
                return (
                    <div className="flex flex-col gap-2">
                        <InputWithSuggestionsDropdown
                            data-attr="site_url"
                            placeholder={SITE_URL_PLACEHOLDER}
                            value={value || ''}
                            onChange={onChange}
                            suggestions={siteUrls}
                            suggestionsLoading={sitesLoading}
                            searchPlaceholder="Filter verified properties…"
                            emptyMessage="No properties accessible by this account."
                            loadingMessage="Loading from Google…"
                        />
                        {savedValueMissing && (
                            <p className="m-0 text-xs text-warning">
                                The currently saved property <code>{value}</code> isn't in the verified list for the
                                connected Google account. Save anyway if you know it's correct, or pick a different one
                                from the list.
                            </p>
                        )}
                    </div>
                )
            }}
        </LemonField>
    )
}
