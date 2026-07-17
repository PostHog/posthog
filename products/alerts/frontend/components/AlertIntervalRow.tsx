import { useValues } from 'kea'

import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'
import { AvailableFeature } from '~/types'

import { AlertDefinitionRow, AlertNextEvaluationStatus } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import {
    cadenceFinerThanInsightInterval,
    selectAlertCalculationInterval,
} from 'products/alerts/frontend/logic/alertIntervalHelpers'
import {
    AlertType,
    isHogQLAlertConfig,
    isTrendsAlertConfig,
    supportsOngoingInterval,
    supportsTimeWindow,
} from 'products/alerts/frontend/types'

import { getAlertIntervalOptions } from './editAlertModalUtils'

export interface AlertIntervalRowProps {
    alertForm: AlertFormType
    creatingNewAlert: boolean
    alert: AlertType | null | undefined
    trendInterval: string | null | undefined
    nextPlannedEvaluationStale: boolean
    canCheckOngoingInterval: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

function getHogQLEvaluatedText(alertForm: AlertFormType): string {
    if (!isHogQLAlertConfig(alertForm.config)) {
        return ''
    }
    if (alertForm.config.evaluation === 'any_row') {
        return 'and check every row of the result'
    }
    if (alertForm.config.evaluation === 'first_row') {
        return "and evaluate the query's first (newest) row"
    }
    return "and evaluate the query's last (newest) row"
}

export function AlertIntervalRow({
    alertForm,
    creatingNewAlert,
    alert,
    trendInterval,
    nextPlannedEvaluationStale,
    canCheckOngoingInterval,
    onSetAlertFormValue,
}: AlertIntervalRowProps): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const hasHighFrequencyAlertsEntitlement = hasAvailableFeature(AvailableFeature.HIGH_FREQUENCY_ALERTS)
    const hasRealTimeAlertsEntitlement = hasAvailableFeature(AvailableFeature.REAL_TIME_ALERTS)
    const realTimeAlertsEnabled = useFeatureFlag('ALERTS_REAL_TIME_INTERVAL')

    let evaluatedWindow: JSX.Element
    if (!supportsTimeWindow(alertForm.config)) {
        evaluatedWindow = <div>{getHogQLEvaluatedText(alertForm)}</div>
    } else {
        const period =
            isTrendsAlertConfig(alertForm.config) && alertForm.config.check_ongoing_interval ? 'current' : 'last'
        evaluatedWindow = (
            <div data-attr="alertForm-trend-interval">
                and check {period}{' '}
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
        )
    }

    let nextEvaluation: JSX.Element | null = null
    if (!creatingNewAlert && alert) {
        let status: JSX.Element
        if (nextPlannedEvaluationStale) {
            status = <span>We'll recalculate this after you save.</span>
        } else if (alert.next_check_at) {
            status = <TZLabel time={alert.next_check_at} />
        } else {
            status = <span>We're calculating this. This can take a few minutes.</span>
        }
        nextEvaluation = (
            <AlertNextEvaluationStatus loading={!nextPlannedEvaluationStale && !alert.next_check_at}>
                {status}
            </AlertNextEvaluationStatus>
        )
    }

    const scheduleLabel =
        alertForm.calculation_interval === AlertCalculationInterval.REAL_TIME ? 'Run alert' : 'Run alert every'

    return (
        <div className="space-y-2">
            <AlertDefinitionRow label={scheduleLabel}>
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
                                realTimeAlertsEnabled || value === AlertCalculationInterval.REAL_TIME
                            )}
                            onChange={(interval) => {
                                selectAlertCalculationInterval(interval, {
                                    guardAvailableFeature,
                                    onSelect: (selected) => {
                                        onChange(selected)
                                        if (
                                            cadenceFinerThanInsightInterval(selected, trendInterval) &&
                                            canCheckOngoingInterval &&
                                            supportsOngoingInterval(alertForm.config) &&
                                            alertForm.config.check_ongoing_interval === undefined
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
                {evaluatedWindow}
            </AlertDefinitionRow>
            {nextEvaluation}
        </div>
    )
}
