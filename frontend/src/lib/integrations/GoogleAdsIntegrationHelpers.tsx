import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { GoogleAdsConversionActionType, IntegrationType } from '~/types'

import { googleAdsIntegrationLogic } from './googleAdsIntegrationLogic'

const getGoogleAdsAccountOptions = (
    googleAdsAccounts?: { id: string; name: string; parent_id: string; level: string }[] | null
): LemonInputSelectOption[] | null => {
    return googleAdsAccounts
        ? googleAdsAccounts.map((customer) => ({
              key: `${customer.id}/${customer.parent_id}`,
              labelComponent: (
                  <span className="flex items-center">
                      {customer.name} ({customer.id.replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3')})
                  </span>
              ),
              label: `${customer.name} (${customer.id.replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3')})`,
          }))
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
    const { googleAdsAccessibleAccounts, googleAdsAccessibleAccountsLoading } = useValues(
        googleAdsIntegrationLogic({ id: integration.id })
    )
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
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !googleAdsAccessibleAccounts &&
                    !googleAdsAccessibleAccountsLoading &&
                    loadGoogleAdsAccessibleAccounts()
                }
                disabled={disabled}
                mode="single"
                data-attr="select-google-ads-customer-id-channel"
                placeholder="Select a Customer ID..."
                options={
                    googleAdsAccountOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value.replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3'),
                              },
                          ]
                        : [])
                }
                loading={googleAdsAccessibleAccountsLoading}
            />
        </>
    )
}
