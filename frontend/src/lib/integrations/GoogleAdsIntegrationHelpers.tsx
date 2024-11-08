import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { GoogleAdsConversionActionType, IntegrationType } from '~/types'

import { googleAdsIntegrationLogic } from './googleAdsIntegrationLogic'

const getGoogleAdsAccountOptions = (googleAdsAccounts?: { id: string }[] | null): LemonInputSelectOption[] | null => {
    return googleAdsAccounts
        ? googleAdsAccounts.map((customerId) => ({
              key: customerId.id.split('/')[1],
              labelComponent: (
                  <span className="flex items-center">
                      {customerId.id.split('/')[1].replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3')}
                  </span>
              ),
              label: `${customerId.id.split('/')[1].replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3')}`,
          }))
        : null
}

const getGoogleAdsConversionActionOptions = (
    googleAdsConversionActions?: GoogleAdsConversionActionType[] | null
): LemonInputSelectOption[] | null => {
    return googleAdsConversionActions
        ? googleAdsConversionActions.map(({ id, name }) => ({
              key: id,
              labelComponent: <span className="flex items-center">{name}</span>,
              label: name,
          }))
        : null
}

export type GoogleAdsPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
    requiredFieldValue?: string
}

export function GoogleAdsConversionActionPicker({
    onChange,
    value,
    requiredFieldValue,
    integration,
    disabled,
}: GoogleAdsPickerProps): JSX.Element {
    const { googleAdsConversionActions, googleAdsConversionActionsLoading } = useValues(
        googleAdsIntegrationLogic({ id: integration.id })
    )
    const { loadGoogleAdsConversionActions } = useActions(googleAdsIntegrationLogic({ id: integration.id }))

    const googleAdsAccountOptions = useMemo(
        () => getGoogleAdsConversionActionOptions(googleAdsConversionActions),
        [googleAdsConversionActions]
    )

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !googleAdsConversionActions &&
                    !googleAdsConversionActionsLoading &&
                    requiredFieldValue &&
                    loadGoogleAdsConversionActions(requiredFieldValue)
                }
                disabled={disabled}
                mode="single"
                data-attr="select-google-ads-conversion-action"
                placeholder="Select a Conversion Action..."
                options={
                    googleAdsAccountOptions ??
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
                                  label: value,
                              },
                          ]
                        : [])
                }
                loading={googleAdsAccessibleAccountsLoading}
            />
        </>
    )
}
