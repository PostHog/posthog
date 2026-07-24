import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { AlertAdvancedOptions } from 'products/alerts/frontend/components/AlertAdvancedOptions'
import { AlertFormType, ongoingIntervalField } from 'products/alerts/frontend/logic/alertFormLogic'
import { isSubDailyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { QuietHoursFields } from './QuietHoursFields'

export interface AlertAdvancedOptionsSectionProps {
    alertForm: AlertFormType
    canCheckOngoingInterval: boolean
    projectTimezone: string
    enabledAdvancedOptionsCount: number
    defaultOpen?: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function AlertAdvancedOptionsSection({
    alertForm,
    canCheckOngoingInterval,
    projectTimezone,
    enabledAdvancedOptionsCount,
    defaultOpen,
    onSetAlertFormValue,
}: AlertAdvancedOptionsSectionProps): JSX.Element {
    const ongoing = ongoingIntervalField(alertForm.config, canCheckOngoingInterval)

    return (
        <AlertAdvancedOptions enabledCount={enabledAdvancedOptionsCount} defaultOpen={defaultOpen}>
            {ongoing.show ? (
                <Group name={['config']}>
                    <div className="flex gap-1">
                        <LemonField name="check_ongoing_interval">
                            <LemonCheckbox
                                checked={ongoing.checked}
                                data-attr="alertForm-check-ongoing-interval"
                                fullWidth
                                label="Check ongoing period"
                                disabledReason={ongoing.disabledReason}
                            />
                        </LemonField>
                        <Tooltip title={ongoing.tooltip} placement="right" delayMs={0}>
                            <IconInfo className="text-xl text-secondary shrink-0" />
                        </Tooltip>
                    </div>
                </Group>
            ) : null}
            <LemonField name="skip_weekend">
                <LemonCheckbox
                    checked={
                        (alertForm.calculation_interval === AlertCalculationInterval.DAILY ||
                            isSubDailyAlertInterval(alertForm.calculation_interval)) &&
                        alertForm.skip_weekend
                    }
                    data-attr="alertForm-skip-weekend"
                    fullWidth
                    label="Skip checking on weekends"
                    disabledReason={
                        alertForm.calculation_interval !== AlertCalculationInterval.DAILY &&
                        !isSubDailyAlertInterval(alertForm.calculation_interval)
                            ? 'Can only skip weekend checking for 15-minute, hourly, or daily alerts'
                            : undefined
                    }
                />
            </LemonField>
            <QuietHoursFields
                scheduleRestriction={alertForm.schedule_restriction}
                calculationInterval={alertForm.calculation_interval}
                teamTimezone={projectTimezone}
                onChange={(next) => onSetAlertFormValue('schedule_restriction', next)}
            />
        </AlertAdvancedOptions>
    )
}
