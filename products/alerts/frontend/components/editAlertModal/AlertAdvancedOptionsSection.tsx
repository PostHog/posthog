import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonCollapse, Tooltip } from '@posthog/lemon-ui'

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { isHighFrequencyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { QuietHoursFields } from '../QuietHoursFields'

export interface AlertAdvancedOptionsSectionProps {
    alertForm: AlertFormType
    canCheckOngoingInterval: boolean
    projectTimezone: string
    enabledAdvancedOptionsCount: number
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function AlertAdvancedOptionsSection({
    alertForm,
    canCheckOngoingInterval: can_check_ongoing_interval,
    projectTimezone,
    enabledAdvancedOptionsCount,
    onSetAlertFormValue,
}: AlertAdvancedOptionsSectionProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <LemonCollapse
                panels={[
                    {
                        key: 'advanced',
                        header: {
                            type: enabledAdvancedOptionsCount > 0 ? 'primary' : 'tertiary',
                            children: (
                                <span className="flex w-full min-w-0 items-center justify-between gap-2">
                                    <span className="min-w-0">Advanced options</span>
                                    {enabledAdvancedOptionsCount > 0 ? (
                                        <span
                                            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-current/20 bg-current/10 text-xs font-semibold tabular-nums leading-none"
                                            aria-label={`${enabledAdvancedOptionsCount} advanced option${
                                                enabledAdvancedOptionsCount === 1 ? '' : 's'
                                            } on`}
                                        >
                                            {enabledAdvancedOptionsCount}
                                        </span>
                                    ) : null}
                                </span>
                            ),
                        },
                        content: (
                            <div className="space-y-2">
                                <Group name={['config']}>
                                    <div className="flex gap-1">
                                        <LemonField name="check_ongoing_interval">
                                            <LemonCheckbox
                                                checked={
                                                    can_check_ongoing_interval &&
                                                    alertForm?.config.check_ongoing_interval
                                                }
                                                data-attr="alertForm-check-ongoing-interval"
                                                fullWidth
                                                label="Check ongoing period"
                                                disabledReason={
                                                    !can_check_ongoing_interval &&
                                                    'Can only alert for ongoing period when checking for absolute value/increase above a set upper threshold.'
                                                }
                                            />
                                        </LemonField>
                                        <Tooltip
                                            title="Checks the insight value for the ongoing period (current week/month) that hasn't yet completed. Use this if you want to be alerted right away when the insight value rises/increases above threshold"
                                            placement="right"
                                            delayMs={0}
                                        >
                                            <IconInfo />
                                        </Tooltip>
                                    </div>
                                </Group>
                                <LemonField name="skip_weekend">
                                    <LemonCheckbox
                                        checked={
                                            (alertForm?.calculation_interval === AlertCalculationInterval.DAILY ||
                                                isHighFrequencyAlertInterval(
                                                    alertForm?.calculation_interval ?? AlertCalculationInterval.DAILY
                                                )) &&
                                            alertForm?.skip_weekend
                                        }
                                        data-attr="alertForm-skip-weekend"
                                        fullWidth
                                        label="Skip checking on weekends"
                                        disabledReason={
                                            alertForm?.calculation_interval !== AlertCalculationInterval.DAILY &&
                                            !isHighFrequencyAlertInterval(
                                                alertForm?.calculation_interval ?? AlertCalculationInterval.DAILY
                                            ) &&
                                            'Can only skip weekend checking for 15-minute, hourly, or daily alerts'
                                        }
                                    />
                                </LemonField>
                                <QuietHoursFields
                                    scheduleRestriction={alertForm.schedule_restriction}
                                    calculationInterval={alertForm.calculation_interval}
                                    teamTimezone={projectTimezone}
                                    onChange={(next) => onSetAlertFormValue('schedule_restriction', next)}
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
