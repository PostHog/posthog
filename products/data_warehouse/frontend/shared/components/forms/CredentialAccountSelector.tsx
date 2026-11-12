import { useActions, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext, useEffect, useMemo, useRef } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { credentialAccountsLogic } from 'lib/integrations/credentialAccountsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { IntegrationAccountApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { InputSuggestion, InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

export interface CredentialAccountSelectorProps {
    fieldName: string
    fieldLabel: string
    /** Sibling payload fields whose values the listing needs, named by the field config. */
    credentialFields: string[]
    /** Name of an OAuth integration id field that lists the same accounts. When the form holds a
     *  value there, it stands in for `credentialFields`, which the other auth branch leaves empty. */
    integrationField?: string
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

/** The account to put in an empty field: the only one a listing found, or null when there is a
 *  choice to make, nothing to pick, or a value the user already entered. */
export function accountToAutoFill(
    accounts: IntegrationAccountApi[],
    accountsError: string | null,
    currentValue: unknown
): string | null {
    const hasValue = currentValue !== undefined && currentValue !== null && String(currentValue).trim() !== ''
    if (accountsError || accounts.length !== 1 || hasValue) {
        return null
    }
    return accounts[0].value
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
    const { sourceType, credentialFields, integrationField, fieldName, fieldLabel, placeholder, caption } = props
    const values = useValues(formLogic) as Record<string, any> | null
    const payload = values?.[formKey]?.payload
    // A connected account answers the same listing, and the two branches are never both filled in,
    // so prefer whichever one the form holds rather than requiring the typed-in set.
    const credentials =
        (integrationField ? collectCredentials(payload, [integrationField]) : undefined) ??
        collectCredentials(payload, credentialFields)

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

    // Fill the field when the credentials can read exactly one account: there is nothing to choose,
    // and an empty field fails the connect step. Each listing is judged once, on arrival, so a user
    // who clears or changes the value is not overridden, and a listing for the previous credentials
    // is never applied to the next ones.
    const ownValue = payload?.[fieldName]
    const judgedListing = useRef<IntegrationAccountApi[] | null>(null)
    useEffect(() => {
        if (accountsLoading || judgedListing.current === accounts) {
            return
        }
        judgedListing.current = accounts
        const fill = accountToAutoFill(accounts, accountsError, ownValue)
        if (fill === null) {
            return
        }
        const setValueAction = formLogic.actions[`set${formKey.charAt(0).toUpperCase()}${formKey.slice(1)}Value`]
        setValueAction?.(['payload', fieldName], fill)
    }, [accounts, accountsLoading, accountsError, ownValue, formLogic, formKey, fieldName])

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
                                : integrationField
                                  ? 'Connect your account above to list accounts.'
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
