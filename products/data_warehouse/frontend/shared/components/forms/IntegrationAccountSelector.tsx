import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo, useRef } from 'react'

import { LemonInput, LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import { integrationAccountsLogic } from 'lib/integrations/integrationAccountsLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import type { LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
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
    /** Multi-select mode: the field's payload value is a string[] and renders as chips. */
    multiple?: boolean
    /** Legacy single-value payload field that seeds the multi picker when it's still empty
     *  (e.g. GitHub sources saved before multi-repo support store `repository`). */
    legacySingleField?: string
}

/** Coerce a form value into the multi picker's string[] shape: undefined/'' -> [],
 *  a lone string -> [string], arrays get trimmed and deduped. */
export function normalizeMultiValue(value: unknown, legacySingle?: unknown): string[] {
    const raw = value === undefined || value === null || value === '' ? [] : Array.isArray(value) ? value : [value]
    const source = raw.length > 0 ? raw : legacySingle ? [legacySingle] : []
    const normalized: string[] = []
    for (const entry of source) {
        const trimmed = String(entry).trim()
        if (trimmed && !normalized.includes(trimmed)) {
            normalized.push(trimmed)
        }
    }
    return normalized
}

/** Generic account/resource picker for OAuth ad sources: a dropdown of the connected integration's
 *  accounts (shared IntegrationAccount contract), falling back to a text input until one is connected. */
export function IntegrationAccountSelector(props: IntegrationAccountSelectorProps): JSX.Element {
    // Only mount the hook-using inner component once inside a kea <Form>, to avoid a null logic.
    const formContext = useContext(FormContext)
    if (!formContext.logic) {
        return props.multiple ? <MultiAccountField {...props} /> : <AccountTextField {...props} />
    }
    return <IntegrationAccountSelectorInner {...props} formLogic={formContext.logic} formKey={formContext.formKey} />
}

function IntegrationAccountSelectorInner({
    formLogic,
    formKey,
    ...props
}: IntegrationAccountSelectorProps & { formLogic: any; formKey: string }): JSX.Element {
    const integrationId = useFormIntegrationId(formLogic, formKey, props.integrationField)
    const legacySingleValue = useFormFieldValue(formLogic, formKey, props.legacySingleField)
    const ownValue = useFormFieldValue(formLogic, formKey, props.fieldName)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    // Seed the multi field's form state from the legacy single-value field (e.g. a pre-multi-repo
    // GitHub source's `repository`) so an untouched edit still validates and saves the full list.
    // Seed at most once per mount: re-seeding whenever the field is empty would instantly undo a
    // user removing the last chip (e.g. to swap the single repo for another one).
    const { fieldName, multiple } = props
    const seededLegacyValue = useRef(false)
    useEffect(() => {
        if (!multiple || seededLegacyValue.current || normalizeMultiValue(ownValue).length > 0) {
            return
        }
        const seeded = normalizeMultiValue(undefined, legacySingleValue)
        if (seeded.length === 0) {
            return
        }
        seededLegacyValue.current = true
        const setValueAction = formLogic.actions[`set${formKey.charAt(0).toUpperCase()}${formKey.slice(1)}Value`]
        setValueAction?.(['payload', fieldName], seeded)
    }, [multiple, ownValue, legacySingleValue, formLogic, formKey, fieldName])

    const integrationIsValid = useMemo(() => {
        if (!integrationId || integrationsLoading || !integrations) {
            return false
        }
        return integrations.some(
            (integration) => integration.id === integrationId && integration.kind === props.integrationKind
        )
    }, [integrationId, integrations, integrationsLoading, props.integrationKind])

    if (props.multiple) {
        return (
            <MultiAccountField
                {...props}
                integrationId={integrationIsValid && integrationId ? integrationId : undefined}
            />
        )
    }

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

/** Find the value stored under `key` anywhere in a (possibly nested) payload object. The OAuth id a
 *  picker depends on is usually a top-level field, but some sources nest it under a select group
 *  (e.g. GitHub's `github_integration_id` lives inside the `auth_method` select), so we look for the
 *  field wherever it is rather than assuming the top level. */
function findFieldValue(obj: unknown, key: string): unknown {
    if (!obj || typeof obj !== 'object') {
        return undefined
    }
    const record = obj as Record<string, unknown>
    if (key in record) {
        return record[key]
    }
    for (const nested of Object.values(record)) {
        const found = findFieldValue(nested, key)
        if (found !== undefined) {
            return found
        }
    }
    return undefined
}

function useFormFieldValue(formLogic: any, formKey: string, fieldName: string | undefined): unknown {
    const values = useValues(formLogic) as Record<string, any> | null
    if (!values || !fieldName) {
        return undefined
    }
    return findFieldValue(values[formKey]?.payload, fieldName)
}

function useFormIntegrationId(formLogic: any, formKey: string, integrationField: string): number | undefined {
    const values = useValues(formLogic) as Record<string, any> | null
    if (!values) {
        return undefined
    }
    // Saved job_inputs store the id as a JSONB string; coerce so `integration.id === id` matches.
    const raw = findFieldValue(values[formKey]?.payload, integrationField)
    const id = raw === undefined || raw === null || raw === '' ? undefined : Number(raw)
    return id !== undefined && Number.isFinite(id) ? id : undefined
}

const OWNER_REPO_PATTERN = /^[^/\s]+\/[^/\s]+$/

function accountOptionLabel(displayName: string, value: string, isPrimary: boolean, badges: string[]): JSX.Element {
    // When display_name === value (e.g. GSC site url), "value (value)" is redundant.
    const labelText = displayName === value ? displayName : `${displayName} (${value})`
    return (
        <div className="flex items-center gap-2">
            <span>{labelText}</span>
            {isPrimary && <LemonTag type="primary">Primary</LemonTag>}
            {badges.map((badge) => (
                <LemonTag type="muted" key={badge}>
                    {badge}
                </LemonTag>
            ))}
        </div>
    )
}

/** Multi-select variant: chips of selected values, with the connected integration's accounts as
 *  async-searched options (or free entry only, e.g. on the PAT path where there's no integration). */
function MultiAccountField({
    integrationId,
    sourceType,
    fieldName,
    fieldLabel,
    placeholder,
    caption,
}: IntegrationAccountSelectorProps & { integrationId?: number }): JSX.Element {
    if (integrationId) {
        return (
            <MultiAccountFieldWithOptions
                integrationId={integrationId}
                sourceType={sourceType}
                fieldName={fieldName}
                fieldLabel={fieldLabel}
                placeholder={placeholder}
                caption={caption}
            />
        )
    }
    return (
        <MultiAccountFieldInner
            fieldName={fieldName}
            fieldLabel={fieldLabel}
            placeholder={placeholder}
            caption={caption}
            options={[]}
        />
    )
}

function MultiAccountFieldWithOptions({
    integrationId,
    sourceType,
    fieldName,
    fieldLabel,
    placeholder,
    caption,
}: {
    integrationId: number
    sourceType: string
    fieldName: string
    fieldLabel: string
    placeholder?: string
    caption?: string
}): JSX.Element {
    const { accounts, accountsLoading, accountsError } = useValues(
        integrationAccountsLogic({ id: integrationId, sourceType })
    )
    const { loadAccounts, setSearch } = useActions(integrationAccountsLogic({ id: integrationId, sourceType }))

    useEffect(() => {
        loadAccounts()
    }, [loadAccounts])

    const options = useMemo<LemonInputSelectOption[]>(() => {
        const sorted = [...accounts].sort((a, b) => Number(b.is_primary) - Number(a.is_primary))
        return sorted.map((account) => ({
            key: account.value,
            label:
                account.display_name === account.value ? account.value : `${account.display_name} (${account.value})`,
            labelComponent: accountOptionLabel(account.display_name, account.value, account.is_primary, account.badges),
        }))
    }, [accounts])

    return (
        <MultiAccountFieldInner
            fieldName={fieldName}
            fieldLabel={fieldLabel}
            placeholder={placeholder}
            caption={caption}
            options={options}
            loading={accountsLoading}
            onInputChange={setSearch}
            error={accountsError ?? undefined}
        />
    )
}

function MultiAccountFieldInner({
    fieldName,
    fieldLabel,
    placeholder,
    caption,
    options,
    loading,
    onInputChange,
    error,
}: {
    fieldName: string
    fieldLabel: string
    placeholder?: string
    caption?: string
    options: LemonInputSelectOption[]
    loading?: boolean
    onInputChange?: (value: string) => void
    error?: string
}): JSX.Element {
    return (
        <LemonField name={fieldName} label={fieldLabel} help={captionHelp(caption)}>
            {({ value, onChange }) => {
                // The legacy single value is seeded into form state once (see IntegrationAccountSelectorInner),
                // so render the form value as-is — falling back here would resurrect a chip the user removed.
                const selected = normalizeMultiValue(value)
                const malformed = selected.filter((entry) => !OWNER_REPO_PATTERN.test(entry))
                return (
                    <div className="flex flex-col gap-2">
                        <LemonInputSelect
                            data-attr={fieldName}
                            mode="multiple"
                            allowCustomValues
                            placeholder={placeholder}
                            value={selected}
                            onChange={(newValues) => onChange(normalizeMultiValue(newValues))}
                            options={options}
                            loading={loading}
                            onInputChange={onInputChange}
                        />
                        {error && <p className="m-0 text-xs text-warning">{error}</p>}
                        {malformed.length > 0 && (
                            <p className="m-0 text-xs text-warning">
                                These entries don't look like <code>owner/repo</code>:{' '}
                                {malformed.map((entry) => `"${entry}"`).join(', ')}. Double-check them before saving.
                            </p>
                        )}
                    </div>
                )
            }}
        </LemonField>
    )
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
    const { loadAccounts, setSearch } = useActions(integrationAccountsLogic({ id: integrationId, sourceType }))

    useEffect(() => {
        loadAccounts()
    }, [loadAccounts])

    const suggestions = useMemo<InputSuggestion[]>(() => {
        const sorted = [...accounts].sort((a, b) => Number(b.is_primary) - Number(a.is_primary))
        return sorted.map((account) => {
            const searchText =
                account.display_name === account.value
                    ? `${account.value} ${account.secondary_text ?? ''}`
                    : `${account.display_name} ${account.value} ${account.secondary_text ?? ''}`
            return {
                value: account.value,
                label: accountOptionLabel(account.display_name, account.value, account.is_primary, account.badges),
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
                            onSearchChange={setSearch}
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
