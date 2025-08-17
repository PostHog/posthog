import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { IntegrationType, LinkedInAdsAccountType, LinkedInAdsConversionRuleType } from '~/types'

import { linkedInAdsIntegrationLogic } from './linkedInAdsIntegrationLogic'

const getLinkedInAdsAccountOptions = (
    linkedInAdsAccounts?: LinkedInAdsAccountType[] | null
): LemonInputSelectOption[] | null => {
    return linkedInAdsAccounts
        ? linkedInAdsAccounts.map((account) => ({
              key: account.id.toString(),
              labelComponent: (
                  <span className="flex items-center">
                      {account.name} ({account.id.toString()})
                  </span>
              ),
              label: `${account.name}`,
          }))
        : null
}

const getLinkedInAdsConversionRuleOptions = (
    linkedInAdsConversionRules?: LinkedInAdsConversionRuleType[] | null
): LemonInputSelectOption[] | null => {
    return linkedInAdsConversionRules
        ? linkedInAdsConversionRules.map(({ id, name }) => ({
              key: id.toString(),
              labelComponent: (
                  <span className="flex items-center">
                      {name} ({id})
                  </span>
              ),
              label: `${name} (${id})`,
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

    useEffect(() => {
        if (requiresFieldValue) {
            loadLinkedInAdsConversionRules(requiresFieldValue)
        }
    }, [loadLinkedInAdsConversionRules, requiresFieldValue])

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
    const { linkedInAdsAccounts, linkedInAdsAccountsLoading } = useValues(
        linkedInAdsIntegrationLogic({ id: integration.id })
    )
    const { loadLinkedInAdsAccounts } = useActions(linkedInAdsIntegrationLogic({ id: integration.id }))

    const linkedInAdsAccountOptions = useMemo(
        () => getLinkedInAdsAccountOptions(linkedInAdsAccounts),
        [linkedInAdsAccounts]
    )

    useOnMountEffect(() => {
        if (!disabled) {
            loadLinkedInAdsAccounts()
        }
    })

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() => !linkedInAdsAccounts && !linkedInAdsAccountsLoading && loadLinkedInAdsAccounts()}
                disabled={disabled}
                mode="single"
                data-attr="select-linkedin-ads-customer-id-channel"
                placeholder="Select a Account ID..."
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
                loading={linkedInAdsAccountsLoading}
            />
        </>
    )
}
