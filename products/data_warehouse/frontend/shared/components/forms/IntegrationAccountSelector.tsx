import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo } from 'react'

import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import { integrationAccountsLogic } from 'lib/integrations/integrationAccountsLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { InputSuggestion, InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

export interface IntegrationAccountSelectorProps {
    fieldName: string
    fieldLabel: string
    /** Which OAuth id field of the form payload to read, e.g. "bing_ads_integration_id". */
    integrationField: string
    /** Integration kind used to validate the connected integration, e.g. "bing-ads". */
    integrationKind: string
    /** Data warehouse source type used to route the generic accounts endpoint, e.g. "BingAds". */
    sourceType: string
    placeholder?: string
    /** Optional format guidance rendered under the field label. */
    caption?: string
}

/** Generic account/resource picker for OAuth ad sources: a dropdown of the connected integration's
 *  accounts (shared IntegrationAccount contract), falling back to a text input until one is connected. */
export function IntegrationAccountSelector(props: IntegrationAccountSelectorProps): JSX.Element {
    // Only mount the hook-using inner component once inside a kea <Form>, to avoid a null logic.
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

function captionHelp(caption?: string): JSX.Element | undefined {
    return caption ? <LemonMarkdown className="text-xs">{caption}</LemonMarkdown> : undefined
}

function AccountTextField({
    fieldName,
    fieldLabel,
    placeholder,
    caption,
}: IntegrationAccountSelectorProps): JSX.Element {
    return (
        <LemonField name={fieldName} label={fieldLabel} help={captionHelp(caption)}>
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
    const values = useValues(formLogic) as Record<string, any> | null
    if (!values) {
        return undefined
    }
    // Saved job_inputs store the id as a JSONB string; coerce so `integration.id === id` matches.
    const raw = values[formKey]?.payload?.[integrationField]
    const id = raw === undefined || raw === null || raw === '' ? undefined : Number(raw)
    return id && Number.isFinite(id) ? id : undefined
}

function IntegrationAccountFieldWithDropdown({
    integrationId,
    sourceType,
    fieldName,
    fieldLabel,
    placeholder,
    caption,
}: IntegrationAccountSelectorProps & { integrationId: number }): JSX.Element {
    const { accounts, accountsLoading, accountsError } = useValues(
        integrationAccountsLogic({ id: integrationId, sourceType })
    )
    const { loadAccounts } = useActions(integrationAccountsLogic({ id: integrationId, sourceType }))

    useEffect(() => {
        loadAccounts()
    }, [loadAccounts])

    const suggestions = useMemo<InputSuggestion[]>(() => {
        const sorted = [...accounts].sort((a, b) => Number(b.is_primary) - Number(a.is_primary))
        return sorted.map((account) => {
            // When display_name === value (e.g. GSC site url), "value (value)" is redundant.
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
        <LemonField name={fieldName} label={fieldLabel} help={captionHelp(caption)}>
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
                        {accountsError && <p className="m-0 text-xs text-warning">{accountsError}</p>}
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
