import { Group } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonCollapse, Tooltip } from '@posthog/lemon-ui'

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { isFunnelsAlertConfig, isTrendsAlertConfig, supportsOngoingInterval } from 'lib/components/Alerts/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { isHighFrequencyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { QuietHoursFields } from '../QuietHoursFields'

export interface AlertAdvancedOptionsSectionProps {
    alertForm: AlertFormType
    canCheckOngoingInterval: boolean
    /** Historical-trend funnels are a time series, so they can check the ongoing period too; steps
     * funnels can't, so the funnel ongoing toggle is gated on this. */
    isTrendsFunnel: boolean
    projectTimezone: string
    enabledAdvancedOptionsCount: number
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function AlertAdvancedOptionsSection({
    alertForm,
    canCheckOngoingInterval: can_check_ongoing_interval,
    isTrendsFunnel,
    projectTimezone,
    enabledAdvancedOptionsCount,
    onSetAlertFormValue,
}: AlertAdvancedOptionsSectionProps): JSX.Element {
    const config = alertForm?.config
    const ongoingIsFunnel = isFunnelsAlertConfig(config)
    // Trends alerts apply unconditionally; historical-trend funnels only (steps funnels aren't a series).
    const showOngoingInterval = supportsOngoingInterval(config) && (isTrendsAlertConfig(config) || isTrendsFunnel)
    // Funnel rates aren't monotonic over a partial period, so the funnel toggle is ungated — unlike trends,
    // which only allow it for absolute-value/increase above an upper threshold.
    const ongoingChecked =
        (isTrendsAlertConfig(config) || isFunnelsAlertConfig(config)) &&
        !!config.check_ongoing_interval &&
        (ongoingIsFunnel || can_check_ongoing_interval)
    const ongoingDisabledReason =
        ongoingIsFunnel || can_check_ongoing_interval
            ? undefined
            : 'Can only alert for ongoing period when checking for absolute value/increase above a set upper threshold.'
    const ongoingTooltip = ongoingIsFunnel
        ? 'By default the alert uses the most recently completed period. Enable this to evaluate the current, still-in-progress period instead — useful to be alerted sooner, at the cost of a partial datapoint.'
        : "Checks the insight value for the ongoing period (current week/month) that hasn't yet completed. Use this if you want to be alerted right away when the insight value rises/increases above threshold"
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
                                {showOngoingInterval && (
                                    <Group name={['config']}>
                                        <div className="flex gap-1">
                                            <LemonField name="check_ongoing_interval">
                                                <LemonCheckbox
                                                    checked={ongoingChecked}
                                                    data-attr="alertForm-check-ongoing-interval"
                                                    fullWidth
                                                    label="Check ongoing period"
                                                    disabledReason={ongoingDisabledReason}
                                                />
                                            </LemonField>
                                            <Tooltip title={ongoingTooltip} placement="right" delayMs={0}>
                                                <IconInfo />
                                            </Tooltip>
                                        </div>
                                    </Group>
                                )}
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
