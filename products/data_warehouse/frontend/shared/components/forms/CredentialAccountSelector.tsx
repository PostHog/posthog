import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { credentialAccountsLogic } from 'lib/integrations/credentialAccountsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { InputSuggestion, InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

export interface CredentialAccountSelectorProps {
    fieldName: string
    fieldLabel: string
    /** Sibling payload fields whose values the listing needs, named by the field config. */
    credentialFields: string[]
    /** Data warehouse source type used to route the listing endpoint, e.g. "AppleSearchAds". */
    sourceType: string
    placeholder?: string
    /** Optional format guidance rendered under the field label. */
    caption?: string
}

/** Pull the named credential fields out of a (possibly nested) form payload.
 *
 * Returns undefined until every one of them has a value: the listing calls the provider, and a
 * request built from a half-filled form can only fail. */
export function collectCredentials(payload: unknown, credentialFields: string[]): Record<string, string> | undefined {
    const collected: Record<string, string> = {}
    for (const name of credentialFields) {
        const value = findFieldValue(payload, name)
        if (value === undefined || value === null || String(value).trim() === '') {
            return undefined
        }
        collected[name] = String(value)
    }
    return collected
}

/** Find the value stored under `key` anywhere in a (possibly nested) payload object. Mirrors the
 *  OAuth picker's lookup: a credential can sit inside a select group rather than at the top level. */
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

/** Account picker for a source whose credentials are typed into the connect form rather than held
 *  by an OAuth integration. The OAuth twin is `IntegrationAccountSelector`; both render the same
 *  free-text-with-suggestions input, so a user who cannot list accounts can always type one. */
export function CredentialAccountSelector(props: CredentialAccountSelectorProps): JSX.Element {
    // Only mount the hook-using inner component inside a kea <Form>, to avoid a null logic.
    const formContext = useContext(FormContext)
    if (!formContext.logic) {
        return <AccountTextField {...props} />
    }
    return <CredentialAccountSelectorInner {...props} formLogic={formContext.logic} formKey={formContext.formKey} />
}

function CredentialAccountSelectorInner({
    formLogic,
    formKey,
    ...props
}: CredentialAccountSelectorProps & { formLogic: any; formKey: string }): JSX.Element {
    const { sourceType, credentialFields, fieldName, fieldLabel, placeholder, caption } = props
    const values = useValues(formLogic) as Record<string, any> | null
    const credentials = collectCredentials(values?.[formKey]?.payload, credentialFields)

    const { accounts, accountsLoading, accountsLoaded, accountsError } = useValues(
        credentialAccountsLogic({ sourceType })
    )
    const { setCredentials } = useActions(credentialAccountsLogic({ sourceType }))

    // Serialized so the effect fires on a changed credential rather than on every render.
    const credentialsKey = credentials ? JSON.stringify(credentials) : ''
    useEffect(() => {
        if (credentialsKey) {
            setCredentials(JSON.parse(credentialsKey))
        }
    }, [credentialsKey, setCredentials])

    const suggestions = useMemo<InputSuggestion[]>(
        () =>
            accounts.map((account) => ({
                value: account.value,
                label:
                    account.display_name === account.value
                        ? account.display_name
                        : `${account.display_name} (${account.value})`,
                searchText: [account.display_name, account.value].join(' '),
            })),
        [accounts]
    )

    return (
        <LemonField name={fieldName} label={fieldLabel} help={captionHelp(caption)}>
            {({ value, onChange }) => (
                <div className="flex flex-col gap-2">
                    <InputWithSuggestionsDropdown
                        data-attr={fieldName}
                        placeholder={placeholder}
                        value={value || ''}
                        onChange={onChange}
                        suggestions={suggestions}
                        suggestionsLoading={accountsLoading}
                        searchPlaceholder="Filter accounts…"
                        emptyMessage={
                            credentials
                                ? "Couldn't load your accounts. Type the value in above."
                                : 'Fill in the credentials above to list accounts.'
                        }
                        noMatchMessage={() => 'No accounts match your filter.'}
                        loadingMessage="Loading accounts…"
                    />
                    {accountsError && <p className="m-0 text-xs text-warning">{accountsError}</p>}
                    {accountsLoaded && !accountsLoading && !accountsError && accounts.length === 0 && (
                        <p className="m-0 text-xs text-warning">
                            These credentials can't read any {fieldLabel} yet. Check the API user's role, or enter the
                            value above if you know it.
                        </p>
                    )}
                </div>
            )}
        </LemonField>
    )
}

function captionHelp(caption?: string): JSX.Element | undefined {
    return caption ? <LemonMarkdown className="text-xs">{caption}</LemonMarkdown> : undefined
}

function AccountTextField({
    fieldName,
    fieldLabel,
    placeholder,
    caption,
}: CredentialAccountSelectorProps): JSX.Element {
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
