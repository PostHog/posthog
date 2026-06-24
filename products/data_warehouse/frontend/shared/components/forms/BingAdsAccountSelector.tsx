import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo } from 'react'

import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import { bingAdsIntegrationLogic } from 'lib/integrations/bingAdsIntegrationLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { InputSuggestion, InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

const ACCOUNT_ID_PLACEHOLDER = 'Numeric Bing Ads Account ID'

/**
 * Renders the Bing Ads `account_id` field as a dropdown of the connected integration's
 * accessible accounts, so the user picks the numeric Account ID instead of typing it.
 *
 * Falls back to a plain text input before the user picks an OAuth account (or when the
 * form's stored integration ID points at a stale integration), so the field stays usable
 * while the integration choice above is being fixed.
 *
 * Works in both contexts that render this field:
 *   - The new-source wizard (`sourceWizardLogic`, form key `sourceConnectionDetails`)
 *   - The existing-source Config tab (`sourceSettingsLogic`, form key `sourceConfig`)
 *
 * We read the OAuth integration ID via `FormContext` from kea-forms instead of binding
 * directly to a specific logic, so this stays decoupled from which scene renders it.
 */
export function BingAdsAccountSelector(): JSX.Element {
    // FormContext.logic is set whenever this field renders inside a kea <Form> (both the
    // new-source wizard and the existing-source config tab do). Only mount the hook-using
    // inner component when it's present, so we never pass a null logic into useValues — and
    // calling the hook conditionally here would itself violate the rules of hooks.
    const formContext = useContext(FormContext)
    if (!formContext.logic) {
        return <AccountIdTextField />
    }
    return <BingAdsAccountSelectorInner formLogic={formContext.logic} formKey={formContext.formKey} />
}

function BingAdsAccountSelectorInner({ formLogic, formKey }: { formLogic: any; formKey: string }): JSX.Element {
    const integrationId = useFormIntegrationId(formLogic, formKey)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const integrationIsValid = useMemo(() => {
        if (!integrationId || integrationsLoading || !integrations) {
            return false
        }
        return integrations.some((integration) => integration.id === integrationId && integration.kind === 'bing-ads')
    }, [integrationId, integrations, integrationsLoading])

    if (integrationIsValid && integrationId) {
        return <BingAdsAccountFieldWithDropdown integrationId={integrationId} />
    }

    return <AccountIdTextField />
}

function AccountIdTextField(): JSX.Element {
    return (
        <LemonField name="account_id" label="Account ID">
            {({ value, onChange }) => (
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="account_id"
                    placeholder={ACCOUNT_ID_PLACEHOLDER}
                    type="text"
                    value={value || ''}
                    onChange={onChange}
                />
            )}
        </LemonField>
    )
}

function useFormIntegrationId(formLogic: any, formKey: string): number | undefined {
    // formLogic is guaranteed non-null by the caller, so useValues always runs with a valid logic.
    const values = useValues(formLogic) as Record<string, any> | null
    if (!values) {
        return undefined
    }
    // Coerce to number — when the form is hydrated from a saved source's `job_inputs`
    // the integration ID arrives as a string from JSONB. Without the cast, downstream
    // `integration.id === id` lookups in `integrationsLogic` silently miss the match.
    const raw = values[formKey]?.payload?.bing_ads_integration_id
    const id = raw === undefined || raw === null || raw === '' ? undefined : Number(raw)
    return id && Number.isFinite(id) ? id : undefined
}

function BingAdsAccountFieldWithDropdown({ integrationId }: { integrationId: number }): JSX.Element {
    const { accounts, accountsLoading } = useValues(bingAdsIntegrationLogic({ id: integrationId }))
    const { loadAccounts } = useActions(bingAdsIntegrationLogic({ id: integrationId }))

    useEffect(() => {
        loadAccounts()
    }, [loadAccounts])

    const suggestions = useMemo<InputSuggestion[]>(() => {
        const sorted = [...accounts].sort((a, b) => Number(b.is_primary) - Number(a.is_primary))
        return sorted.map((account) => {
            const name = account.name ?? 'Unnamed account'
            return {
                // Persist the numeric id, not the alphanumeric `number` — that's what the backend expects.
                value: String(account.id),
                label: (
                    <div className="flex items-center gap-2">
                        <span>
                            {name} ({account.id})
                        </span>
                        {account.is_primary && <LemonTag type="primary">Primary</LemonTag>}
                        <LemonTag type="muted">{account.status}</LemonTag>
                    </div>
                ),
                searchText: `${name} ${account.id} ${account.number ?? ''}`,
            }
        })
    }, [accounts])

    return (
        <LemonField name="account_id" label="Account ID">
            {({ value, onChange }) => {
                const accountIds = accounts.map((account) => String(account.id))
                const savedValueMissing =
                    !!value && !accountsLoading && accounts.length > 0 && !accountIds.includes(String(value))
                return (
                    <div className="flex flex-col gap-2">
                        <InputWithSuggestionsDropdown
                            data-attr="account_id"
                            placeholder={ACCOUNT_ID_PLACEHOLDER}
                            value={value || ''}
                            onChange={onChange}
                            suggestions={suggestions}
                            suggestionsLoading={accountsLoading}
                            searchPlaceholder="Filter accounts…"
                            emptyMessage="No accounts accessible by this integration."
                            loadingMessage="Loading from Bing…"
                        />
                        {savedValueMissing && (
                            <p className="m-0 text-xs text-warning">
                                The currently saved Account ID <code>{value}</code> isn't in the accessible list for the
                                connected Bing Ads account. Save anyway if you know it's correct, or pick a different
                                one from the list.
                            </p>
                        )}
                    </div>
                )
            }}
        </LemonField>
    )
}
