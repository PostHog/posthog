import { IconClock } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { AlertType } from 'lib/components/Alerts/types'
import { TZLabel } from 'lib/components/TZLabel'
import type { GuardAvailableFeatureFn } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { selectAlertCalculationInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { getAlertIntervalOptions } from './editAlertModalUtils'

export interface AlertIntervalRowProps {
    alertForm: AlertFormType
    creatingNewAlert: boolean
    alert: AlertType | null | undefined
    trendInterval: string | null | undefined
    alerts15MinuteIntervalEnabled: boolean
    hasHighFrequencyAlertsEntitlement: boolean
    guardAvailableFeature: GuardAvailableFeatureFn
    nextPlannedEvaluationStale: boolean
}

export function AlertIntervalRow({
    alertForm,
    creatingNewAlert,
    alert,
    trendInterval,
    alerts15MinuteIntervalEnabled,
    hasHighFrequencyAlertsEntitlement,
    guardAvailableFeature,
    nextPlannedEvaluationStale,
}: AlertIntervalRowProps): JSX.Element {
    return (
        <>
            <div className="flex flex-wrap gap-x-3 gap-y-2 items-center">
                <div>Run alert every</div>
                <LemonField name="calculation_interval">
                    {({ value, onChange }) => (
                        <LemonSelect
                            fullWidth
                            className="w-36 shrink-0 whitespace-nowrap"
                            data-attr="alertForm-calculation-interval"
                            value={value}
                            options={getAlertIntervalOptions(
                                alerts15MinuteIntervalEnabled,
                                hasHighFrequencyAlertsEntitlement
                            )}
                            onChange={(interval) => {
                                selectAlertCalculationInterval(interval, {
                                    guardAvailableFeature,
                                    onSelect: onChange,
                                    hasHighFrequencyAlertsEntitlement,
                                })
                            }}
                        />
                    )}
                </LemonField>
                <div>and check {alertForm?.config.check_ongoing_interval ? 'current' : 'last'}</div>
                <LemonSelect
                    fullWidth
                    className="w-28"
                    data-attr="alertForm-trend-interval"
                    disabledReason={
                        <>
                            To change the interval being checked, edit and <b>save</b> the interval which the insight is
                            'grouped by'
                        </>
                    }
                    value={trendInterval ?? 'day'}
                    options={[
                        {
                            label: trendInterval ?? 'day',
                            value: trendInterval ?? 'day',
                        },
                    ]}
                />
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
