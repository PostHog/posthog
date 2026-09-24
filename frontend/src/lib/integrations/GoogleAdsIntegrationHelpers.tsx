import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption, LemonTag } from '@posthog/lemon-ui'

import { GoogleAdsConversionActionType, IntegrationType } from '~/types'

import { GoogleAdsAccount, googleAdsIntegrationLogic } from './googleAdsIntegrationLogic'

const formatCustomerId = (customerId: string): string => customerId.replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3')

// A picked option carries the account to log in as, as `<customer id>/<login customer id>`. A typed
// value is a bare customer ID, so the account logs in as itself.
export const normalizeCustomerIdValue = (value: string): string | null => {
    const [customerId, loginCustomerId] = value.split('/').map((part) => part.replace(/\D/g, ''))
    return customerId ? `${customerId}/${loginCustomerId || customerId}` : null
}

const getGoogleAdsAccountOptions = (googleAdsAccounts?: GoogleAdsAccount[] | null): LemonInputSelectOption[] | null => {
    return googleAdsAccounts
        ? googleAdsAccounts.map((customer) => {
              const formattedId = formatCustomerId(customer.id)
              return {
                  key: `${customer.id}/${customer.parent_id}`,
                  labelComponent: (
                      <span className="flex items-center gap-1">
                          {customer.name} ({formattedId})
                          {customer.test_account && <LemonTag type="highlight">Test</LemonTag>}
                      </span>
                  ),
                  label: `${customer.name} (${formattedId})${customer.test_account ? ' test' : ''}`,
              }
          })
        : null
}

const getGoogleAdsConversionActionOptions = (
    googleAdsConversionActions?: GoogleAdsConversionActionType[] | null
): LemonInputSelectOption[] | null => {
    return googleAdsConversionActions
        ? googleAdsConversionActions.map(({ id, name }) => ({
              key: id,
              labelComponent: (
                  <span className="flex items-center">
                      {name} ({id})
                  </span>
              ),
              label: `${name} (${id})`,
          }))
        : null
}

export type GoogleAdsPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
    requiresFieldValue?: string
}

export function GoogleAdsConversionActionPicker({
    onChange,
    value,
    requiresFieldValue,
    integration,
    disabled,
}: GoogleAdsPickerProps): JSX.Element {
    const { googleAdsConversionActions, googleAdsConversionActionsLoading } = useValues(
        googleAdsIntegrationLogic({ id: integration.id })
    )
    const { loadGoogleAdsConversionActions } = useActions(googleAdsIntegrationLogic({ id: integration.id }))

    const googleAdsConversionActionOptions = useMemo(
        () => getGoogleAdsConversionActionOptions(googleAdsConversionActions),
        [googleAdsConversionActions]
    )

    useEffect(() => {
        if (requiresFieldValue) {
            loadGoogleAdsConversionActions(requiresFieldValue.split('/')[0], requiresFieldValue.split('/')[1])
        }
    }, [loadGoogleAdsConversionActions, requiresFieldValue])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !googleAdsConversionActions &&
                    !googleAdsConversionActionsLoading &&
                    requiresFieldValue &&
                    loadGoogleAdsConversionActions(requiresFieldValue.split('/')[0], requiresFieldValue.split('/')[1])
                }
                disabled={disabled}
                mode="single"
                data-attr="select-google-ads-conversion-action"
                placeholder="Select a Conversion Action..."
                options={
                    googleAdsConversionActionOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value,
                              },
                          ]
                        : [])
                }
                loading={googleAdsConversionActionsLoading}
            />
        </>
    )
}

export function GoogleAdsCustomerIdPicker({
    onChange,
    value,
    integration,
    disabled,
}: GoogleAdsPickerProps): JSX.Element {
    const { googleAdsAccessibleAccounts, googleAdsAccessibleAccountsLoading, googleAdsAccessibleAccountsError } =
        useValues(googleAdsIntegrationLogic({ id: integration.id }))
    const { loadGoogleAdsAccessibleAccounts } = useActions(googleAdsIntegrationLogic({ id: integration.id }))

    const googleAdsAccountOptions = useMemo(
        () => getGoogleAdsAccountOptions(googleAdsAccessibleAccounts),
        [googleAdsAccessibleAccounts]
    )

    useEffect(() => {
        if (!disabled) {
            loadGoogleAdsAccessibleAccounts()
        }
    }, [loadGoogleAdsAccessibleAccounts, disabled])

    return (
        <div className="flex flex-col gap-1">
            <LemonInputSelect
                onChange={(val) => onChange?.(normalizeCustomerIdValue(val[0] ?? ''))}
                value={value ? [value] : []}
                onFocus={() =>
                    !googleAdsAccessibleAccounts &&
                    !googleAdsAccessibleAccountsLoading &&
                    loadGoogleAdsAccessibleAccounts()
                }
                disabled={disabled}
                mode="single"
                allowCustomValues
                data-attr="select-google-ads-customer-id-channel"
                placeholder="Select a customer ID, or type one..."
                options={
                    googleAdsAccountOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: formatCustomerId(value),
                              },
                          ]
                        : [])
                }
                loading={googleAdsAccessibleAccountsLoading}
            />
            {googleAdsAccessibleAccountsError ? (
                <p className="m-0 text-xs text-warning">
                    {googleAdsAccessibleAccountsError} You can type the 10-digit customer ID of the account you want.
                </p>
            ) : (
                <p className="m-0 text-xs text-secondary">
                    Account missing from the list? Type its 10-digit customer ID.
                </p>
            )}
        </div>
    )
}
