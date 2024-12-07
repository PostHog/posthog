import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IntegrationType, LinkedInAdsConversionRuleType } from '~/types'

import { linkedInAdsIntegrationLogic } from './linkedInAdsIntegrationLogic'

const getLinkedInAdsAccountOptions = (
    linkedInAdsAccounts?: { id: string }[] | null
): LemonInputSelectOption[] | null => {
    return linkedInAdsAccounts
        ? linkedInAdsAccounts.map((customerId) => ({
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

const getLinkedInAdsConversionRuleOptions = (
    linkedInAdsConversionRules?: LinkedInAdsConversionRuleType[] | null
): LemonInputSelectOption[] | null => {
    return linkedInAdsConversionRules
        ? linkedInAdsConversionRules.map(({ id, name }) => ({
              key: id,
              labelComponent: <span className="flex items-center">{name}</span>,
              label: name,
          }))
        : null
}

export type LinkedInAdsPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
    requiresFieldValue?: string
}

export function LinkedInAdsConversionRulePicker({
    onChange,
    value,
    requiresFieldValue,
    integration,
    disabled,
}: LinkedInAdsPickerProps): JSX.Element {
    const { linkedInAdsConversionRules, linkedInAdsConversionRulesLoading } = useValues(
        linkedInAdsIntegrationLogic({ id: integration.id })
    )
    const { loadLinkedInAdsConversionRules } = useActions(linkedInAdsIntegrationLogic({ id: integration.id }))

    const linkedInAdsConversionRuleOptions = useMemo(
        () => getLinkedInAdsConversionRuleOptions(linkedInAdsConversionRules),
        [linkedInAdsConversionRules]
    )

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !linkedInAdsConversionRules &&
                    !linkedInAdsConversionRulesLoading &&
                    requiresFieldValue &&
                    loadLinkedInAdsConversionRules(requiresFieldValue)
                }
                disabled={disabled}
                mode="single"
                data-attr="select-linkedin-ads-conversion-action"
                placeholder="Select a Conversion Action..."
                options={
                    linkedInAdsConversionRuleOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value,
                              },
                          ]
                        : [])
                }
                loading={linkedInAdsConversionRulesLoading}
            />
        </>
    )
}

export function LinkedInAdsAccountIdPicker({
    onChange,
    value,
    integration,
    disabled,
}: LinkedInAdsPickerProps): JSX.Element {
    const { linkedInAdsAccessibleAccounts, linkedInAdsAccessibleAccountsLoading } = useValues(
        linkedInAdsIntegrationLogic({ id: integration.id })
    )
    const { loadLinkedInAdsAccessibleAccounts } = useActions(linkedInAdsIntegrationLogic({ id: integration.id }))

    const linkedInAdsAccountOptions = useMemo(
        () => getLinkedInAdsAccountOptions(linkedInAdsAccessibleAccounts),
        [linkedInAdsAccessibleAccounts]
    )

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !linkedInAdsAccessibleAccounts &&
                    !linkedInAdsAccessibleAccountsLoading &&
                    loadLinkedInAdsAccessibleAccounts()
                }
                disabled={disabled}
                mode="single"
                data-attr="select-linkedin-ads-customer-id-channel"
                placeholder="Select a Customer ID..."
                options={
                    linkedInAdsAccountOptions ??
                    (value
                        ? [
                              {
                                  key: value,
                                  label: value.replace(/(\d{3})(\d{3})(\d{4})/, '$1-$2-$3'),
                              },
                          ]
                        : [])
                }
                loading={linkedInAdsAccessibleAccountsLoading}
            />
        </>
    )
}
