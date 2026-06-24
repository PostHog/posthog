import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo } from 'react'

import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import { integrationAccountsLogic } from 'lib/integrations/integrationAccountsLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { InputSuggestion, InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

export interface IntegrationAccountSelectorProps {
    /** Form field name this selector binds to, e.g. "account_id". */
    fieldName: string
    /** Field label shown above the input, e.g. "Account ID". */
    fieldLabel: string
    /** Which OAuth field of the form's payload holds the integration id, e.g. "bing_ads_integration_id". */
    integrationField: string
    /** Integration `kind` to validate against and route the account fetcher, e.g. "bing-ads". */
    integrationKind: string
    placeholder?: string
}

/**
 * Renders an integration's `{fieldName}` field as a dropdown of the connected integration's
 * accessible accounts (the shared `{ accounts }` contract), so the user picks the stored value
 * instead of typing it. Generic across every ad platform — parametrized by `integrationField`
 * (which OAuth id to read) and `integrationKind` (which integration to validate + fetcher to route).
 *
 * Falls back to a plain text input before the user picks an OAuth account (or when the form's
 * stored integration ID points at a stale integration), so the field stays usable while the
 * integration choice above is being fixed.
 *
 * Works in both contexts that render this field:
 *   - The new-source wizard (`sourceWizardLogic`, form key `sourceConnectionDetails`)
 *   - The existing-source Config tab (`sourceSettingsLogic`, form key `sourceConfig`)
 *
 * We read the OAuth integration ID via `FormContext` from kea-forms instead of binding
 * directly to a specific logic, so this stays decoupled from which scene renders it.
 */
export function IntegrationAccountSelector(props: IntegrationAccountSelectorProps): JSX.Element {
    // FormContext.logic is set whenever this field renders inside a kea <Form> (both the
    // new-source wizard and the existing-source config tab do). Only mount the hook-using
    // inner component when it's present, so we never pass a null logic into useValues — and
    // calling the hook conditionally here would itself violate the rules of hooks.
    const formContext = useContext(FormContext)
    if (!formContext.logic) {
        return <AccountTextField {...props} />
    }
    return <IntegrationAccountSelectorInner {...props} formLogic={formContext.logic} formKey={formContext.formKey} />
}

function IntegrationAccountSelectorInner({
    formLogic,
    formKey,
    ...props
}: IntegrationAccountSelectorProps & { formLogic: any; formKey: string }): JSX.Element {
    const integrationId = useFormIntegrationId(formLogic, formKey, props.integrationField)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const integrationIsValid = useMemo(() => {
        if (!integrationId || integrationsLoading || !integrations) {
            return false
        }
        return integrations.some(
            (integration) => integration.id === integrationId && integration.kind === props.integrationKind
        )
    }, [integrationId, integrations, integrationsLoading, props.integrationKind])

    if (integrationIsValid && integrationId) {
        return <IntegrationAccountFieldWithDropdown {...props} integrationId={integrationId} />
    }

    return <AccountTextField {...props} />
}

function AccountTextField({ fieldName, fieldLabel, placeholder }: IntegrationAccountSelectorProps): JSX.Element {
    return (
        <LemonField name={fieldName} label={fieldLabel}>
            {({ value, onChange }) => (
                <LemonInput
                    className="ph-ignore-input"
                    data-attr={fieldName}
                    placeholder={placeholder}
                    type="text"
                    value={value || ''}
                    onChange={onChange}
                />
            )}
        </LemonField>
    )
}

function useFormIntegrationId(formLogic: any, formKey: string, integrationField: string): number | undefined {
    // formLogic is guaranteed non-null by the caller, so useValues always runs with a valid logic.
    const values = useValues(formLogic) as Record<string, any> | null
    if (!values) {
        return undefined
    }
    // Coerce to number — when the form is hydrated from a saved source's `job_inputs`
    // the integration ID arrives as a string from JSONB. Without the cast, downstream
    // `integration.id === id` lookups in `integrationsLogic` silently miss the match.
    const raw = values[formKey]?.payload?.[integrationField]
    const id = raw === undefined || raw === null || raw === '' ? undefined : Number(raw)
    return id && Number.isFinite(id) ? id : undefined
}

function IntegrationAccountFieldWithDropdown({
    integrationId,
    integrationKind,
    fieldName,
    fieldLabel,
    placeholder,
}: IntegrationAccountSelectorProps & { integrationId: number }): JSX.Element {
    const { accounts, accountsLoading } = useValues(
        integrationAccountsLogic({ id: integrationId, kind: integrationKind })
    )
    const { loadAccounts } = useActions(integrationAccountsLogic({ id: integrationId, kind: integrationKind }))

    useEffect(() => {
        loadAccounts()
    }, [loadAccounts])

    const suggestions = useMemo<InputSuggestion[]>(() => {
        const sorted = [...accounts].sort((a, b) => Number(b.is_primary) - Number(a.is_primary))
        return sorted.map((account) => {
            // When the display name already is the stored value (e.g. Search Console, where both are
            // the site URL) showing "value (value)" is redundant — collapse to a single label.
            const labelText =
                account.display_name === account.value
                    ? account.display_name
                    : `${account.display_name} (${account.value})`
            const searchText =
                account.display_name === account.value
                    ? `${account.value} ${account.secondary_text ?? ''}`
                    : `${account.display_name} ${account.value} ${account.secondary_text ?? ''}`
            return {
                value: account.value,
                label: (
                    <div className="flex items-center gap-2">
                        <span>{labelText}</span>
                        {account.is_primary && <LemonTag type="primary">Primary</LemonTag>}
                        {account.badges.map((badge) => (
                            <LemonTag type="muted" key={badge}>
                                {badge}
                            </LemonTag>
                        ))}
                    </div>
                ),
                searchText,
            }
        })
    }, [accounts])

    return (
        <LemonField name={fieldName} label={fieldLabel}>
            {({ value, onChange }) => {
                const accountValues = accounts.map((account) => account.value)
                const savedValueMissing =
                    !!value && !accountsLoading && accounts.length > 0 && !accountValues.includes(String(value))
                return (
                    <div className="flex flex-col gap-2">
                        <InputWithSuggestionsDropdown
                            data-attr={fieldName}
                            placeholder={placeholder}
                            value={value || ''}
                            onChange={onChange}
                            suggestions={suggestions}
                            suggestionsLoading={accountsLoading}
                            searchPlaceholder="Filter accounts…"
                            emptyMessage="No accounts accessible by this integration."
                            loadingMessage="Loading accounts…"
                        />
                        {savedValueMissing && (
                            <p className="m-0 text-xs text-warning">
                                The currently saved {fieldLabel} <code>{value}</code> isn't in the accessible list for
                                the connected account. Save anyway if you know it's correct, or pick a different one
                                from the list.
                            </p>
                        )}
                    </div>
                )
            }}
        </LemonField>
    )
}
