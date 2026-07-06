import { IconClock } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import {
    AlertType,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
    supportsOngoingInterval,
    supportsTimeWindow,
} from 'lib/components/Alerts/types'
import { TZLabel } from 'lib/components/TZLabel'
import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import {
    cadenceFinerThanInsightInterval,
    selectAlertCalculationInterval,
} from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { getAlertIntervalOptions } from './editAlertModalUtils'

export interface AlertIntervalRowProps {
    alertForm: AlertFormType
    creatingNewAlert: boolean
    alert: AlertType | null | undefined
    trendInterval: string | null | undefined
    hasHighFrequencyAlertsEntitlement: boolean
    hasRealTimeAlertsEntitlement: boolean
    realTimeAlertsEnabled: boolean
    guardAvailableFeature: GuardAvailableFeatureFn
    nextPlannedEvaluationStale: boolean
    canCheckOngoingInterval: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function AlertIntervalRow({
    alertForm,
    creatingNewAlert,
    alert,
    trendInterval,
    hasHighFrequencyAlertsEntitlement,
    hasRealTimeAlertsEntitlement,
    realTimeAlertsEnabled,
    guardAvailableFeature,
    nextPlannedEvaluationStale,
    canCheckOngoingInterval,
    onSetAlertFormValue,
}: AlertIntervalRowProps): JSX.Element {
    const hogqlEvaluation = isHogQLAlertConfig(alertForm.config) ? alertForm.config.evaluation : null
    const hogqlEvaluatedText =
        hogqlEvaluation === 'any_row'
            ? 'and check every row of the result'
            : hogqlEvaluation === 'first_row'
              ? "and evaluate the query's first (newest) row"
              : "and evaluate the query's last (newest) row"
    return (
        <>
            <div className="flex flex-wrap gap-x-3 gap-y-2 items-center">
                <div>
                    {alertForm.calculation_interval === AlertCalculationInterval.REAL_TIME
                        ? 'Run alert'
                        : 'Run alert every'}
                </div>
                <LemonField name="calculation_interval">
                    {({ value, onChange }) => (
                        <LemonSelect
                            fullWidth
                            className="w-36 shrink-0 whitespace-nowrap"
                            data-attr="alertForm-calculation-interval"
                            value={value}
                            options={getAlertIntervalOptions(
                                hasHighFrequencyAlertsEntitlement,
                                hasRealTimeAlertsEntitlement,
                                // Keep the option visible for alerts that already use it, even if the rollout flag is off
                                realTimeAlertsEnabled || value === AlertCalculationInterval.REAL_TIME
                            )}
                            onChange={(interval) => {
                                selectAlertCalculationInterval(interval, {
                                    guardAvailableFeature,
                                    onSelect: (selected) => {
                                        onChange(selected)
                                        // A cadence finer than the insight's bucket re-checks a frozen
                                        // completed value until the bucket closes. Default it to evaluating
                                        // the ongoing bucket so the faster cadence actually does something.
                                        if (
                                            cadenceFinerThanInsightInterval(selected, trendInterval) &&
                                            canCheckOngoingInterval &&
                                            supportsOngoingInterval(alertForm.config)
                                        ) {
                                            onSetAlertFormValue('config', {
                                                ...alertForm.config,
                                                check_ongoing_interval: true,
                                            })
                                        }
                                    },
                                    hasHighFrequencyAlertsEntitlement,
                                    hasRealTimeAlertsEntitlement,
                                })
                            }}
                        />
                    )}
                </LemonField>
                {!supportsTimeWindow(alertForm.config) ? (
                    // SQL queries own their time window — there is no insight interval to echo here,
                    // so state what is actually evaluated instead of a trends-style "check last day".
                    <div>{hogqlEvaluatedText}</div>
                ) : (
                    <div data-attr="alertForm-trend-interval">
                        and check{' '}
                        {isTrendsAlertConfig(alertForm?.config) && alertForm.config.check_ongoing_interval
                            ? 'current'
                            : 'last'}{' '}
                        <Tooltip
                            title={
                                <>
                                    Set by the insight's <b>grouped by</b> interval. Edit the insight to change it.
                                </>
                            }
                        >
                            <span className="font-semibold underline decoration-dotted cursor-help">
                                {trendInterval ?? 'day'}
                            </span>
                        </Tooltip>
                    </div>
                )}
            </div>
            {!creatingNewAlert && alert ? (
                <div className="text-sm text-muted flex flex-wrap items-center gap-x-2 gap-y-0">
                    <IconClock
                        className={`size-4 shrink-0 text-muted motion-reduce:animate-none${
                            !nextPlannedEvaluationStale && !alert.next_check_at ? ' animate-spin' : ''
                        }`}
                        aria-hidden
                    />
                    <span className="shrink-0">Next planned evaluation:</span>
                    {nextPlannedEvaluationStale ? (
                        <span>We'll recalculate this after you save.</span>
                    ) : alert.next_check_at ? (
                        <TZLabel time={alert.next_check_at} />
                    ) : (
                        <span>We're calculating this. This can take a few minutes.</span>
                    )}
                </div>
            ) : null}
        </>
    )
}
