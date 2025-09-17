import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption, Link } from '@posthog/lemon-ui'

import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'

import { IntegrationType, TwilioPhoneNumberType } from '~/types'

import { twilioIntegrationLogic } from './twilioIntegrationLogic'

const getTwilioPhoneNumberOptions = (
    twilioPhoneNumbers?: TwilioPhoneNumberType[] | null
): LemonInputSelectOption[] | null => {
    return twilioPhoneNumbers
        ? twilioPhoneNumbers.map((x) => {
              const displayLabel = `${x.friendly_name} (${x.sid})`
              return {
                  key: x.phone_number,
                  labelComponent: (
                      <span className="flex items-center">
                          <span>{displayLabel}</span>
                      </span>
                  ),
                  label: displayLabel,
              }
          })
        : null
}

export type TwilioPhoneNumberPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
}

export function TwilioPhoneNumberPicker({
    onChange,
    value,
    integration,
    disabled,
}: TwilioPhoneNumberPickerProps): JSX.Element {
    const { twilioPhoneNumbers, allTwilioPhoneNumbersLoading, getPhoneNumberRefreshButtonDisabledReason } = useValues(
        twilioIntegrationLogic({ id: integration.id })
    )
    const { loadAllTwilioPhoneNumbers } = useActions(twilioIntegrationLogic({ id: integration.id }))

    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date `getPhoneNumberRefreshButtonDisabledReason`

    // If twilioPhoneNumbers aren't loaded, make sure we display only the phone number and not the actual underlying value
    const twilioPhoneNumberOptions = useMemo(
        () => getTwilioPhoneNumberOptions(twilioPhoneNumbers),
        [twilioPhoneNumbers]
    )

    // Sometimes the parent will only store the phone number and not the friendly name, so we need to handle that
    const modifiedValue = useMemo(() => {
        const phoneNumber = twilioPhoneNumbers.find((x: TwilioPhoneNumberType) => x.phone_number === value)

        if (phoneNumber) {
            return `${phoneNumber.friendly_name} (${phoneNumber.sid})`
        }

        return value
    }, [value, twilioPhoneNumbers])

    useEffect(() => {
        if (!disabled) {
            loadAllTwilioPhoneNumbers()
        }
    }, [loadAllTwilioPhoneNumbers, disabled])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => onChange?.(val[0] ?? null)}
                value={value ? [value] : []}
                onFocus={() =>
                    !twilioPhoneNumbers.length && !allTwilioPhoneNumbersLoading && loadAllTwilioPhoneNumbers()
                }
                disabled={disabled}
                mode="single"
                data-attr="select-twilio-phone-number"
                placeholder="Select a phone number..."
                action={{
                    children: <span className="Link">Refresh phone numbers</span>,
                    onClick: () => loadAllTwilioPhoneNumbers(true),
                    disabledReason: getPhoneNumberRefreshButtonDisabledReason(),
                }}
                emptyStateComponent={
                    <p className="text-secondary italic p-1">
                        No phone numbers found. Make sure your Twilio account has phone numbers configured.{' '}
                        <Link to="https://posthog.com/docs/cdp/destinations/twilio" target="_blank">
                            See the docs for more information.
                        </Link>
                    </p>
                }
                options={
                    twilioPhoneNumberOptions ??
                    (modifiedValue
                        ? [
                              {
                                  key: value ?? modifiedValue,
                                  label: modifiedValue,
                              },
                          ]
                        : [])
                }
                loading={allTwilioPhoneNumbersLoading}
            />
        </>
    )
}
