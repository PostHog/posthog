import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useMemo } from 'react'

import { IconCalendar, IconChevronLeft } from '@posthog/icons'
import { LemonCheckbox, LemonInput, Link, SpinnerOverlay } from '@posthog/lemon-ui'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { formatDate } from 'lib/utils/datetime'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getDisplayNameFromEntityNode } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AlertCalculationInterval, AlertState } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isFunnelsQuery, isInsightVizNode } from '~/queries/utils'
import { AvailableFeature, FunnelVizType, InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { AlertAdvancedOptionsSection } from 'products/alerts/frontend/components/editAlertModal/AlertAdvancedOptionsSection'
import { AlertDefinitionSection } from 'products/alerts/frontend/components/editAlertModal/AlertDefinitionSection'
import { AlertIntervalRow } from 'products/alerts/frontend/components/editAlertModal/AlertIntervalRow'
import { AlertNotificationSection } from 'products/alerts/frontend/components/editAlertModal/AlertNotificationSection'
import { isHighFrequencyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { alertFormLogic, canCheckOngoingInterval } from '../alertFormLogic'
import { alertLogic } from '../alertLogic'
import { isNextPlannedEvaluationStale } from '../alertSchedulingStale'
import { insightAlertsLogic } from '../insightAlertsLogic'
import { SnoozeButton } from '../SnoozeButton'
import { supportsAnomalyDetection, supportsOngoingInterval } from '../types'
import type { AlertType } from '../types'
import { AlertHistorySection, AlertHistorySectionSkeleton } from './AlertHistorySection'

interface EditAlertModalProps {
    isOpen: boolean | undefined
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    insightLogicProps?: InsightLogicProps
}

export function EditAlertModal({
    isOpen,
    alertId,
    insightId,
    insightShortId,
    onClose,
    onEditSuccess,
    insightLogicProps,
}: EditAlertModalProps): JSX.Element {
    const _alertLogic = alertLogic({ alertId })
    const { alert, alertLoading } = useValues(_alertLogic)

    /** Parent callback only (e.g. close modal). `alertLogic` is hydrated from the save response inside `alertFormLogic`. */
    const _onEditSuccess = useCallback(
        (alertId: AlertType['id'] | undefined) => {
            onEditSuccess(alertId)
        },
        [onEditSuccess]
    )

    const trendsLogic = trendsDataLogic({ dashboardItemId: insightShortId })
    const {
        alertSeries,
        isNonTimeSeriesDisplay,
        isBreakdownValid,
        formulaNodes,
        interval: trendInterval,
    } = useValues(trendsLogic)

    const { query } = useValues(insightVizDataLogic(insightLogicProps ?? { dashboardItemId: insightShortId }))

    const funnelSource = !!query && isInsightVizNode(query) && isFunnelsQuery(query.source) ? query.source : null
    const isFunnelInsight = funnelSource !== null
    // Trends funnels alert on the overall conversion rate over time, so they skip the step picker and
    // the preview reads the latest period instead of a step snapshot. The backend dispatches on the
    // same viz type — see funnel_strategies.py.
    const isTrendsFunnel = funnelSource?.funnelsFilter?.funnelVizType === FunnelVizType.Trends
    const funnelStepLabels = (funnelSource?.series ?? []).map(
        (node, index) => getDisplayNameFromEntityNode(node) ?? `Step ${index + 1}`
    )
    const insightAlertKind: 'hogql' | 'funnels' | 'trends' = containsHogQLQuery(query)
        ? 'hogql'
        : isFunnelInsight
          ? 'funnels'
          : 'trends'

    const formLogicProps = {
        alert,
        insightId,
        onEditSuccess: _onEditSuccess,
        insightVizDataLogicProps: insightLogicProps,
        insightInterval: trendInterval ?? undefined,
        insightAlertKind,
        insightIsTrendsFunnel: isTrendsFunnel,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const {
        alertForm,
        isAlertFormSubmitting,
        simulationResult,
        simulationResultLoading,
        simulationDateFrom,
        thresholdBoundsFormError,
        hogqlAlertPreview,
        funnelAlertPreview,
        hogqlResultColumns,
        hogqlValueColumnOptions,
        hogqlLabelColumnOptions,
    } = useValues(formLogic)
    const {
        deleteAlert,
        snoozeAlert,
        clearSnooze,
        simulateAlert,
        clearSimulation,
        setSimulationDateFrom,
        setAlertFormSubmitAttempted,
    } = useActions(formLogic)
    const { setAlertFormValue } = useActions(formLogic)

    const { currentTeam } = useValues(teamLogic)
    const projectTimezone = currentTeam?.timezone ?? 'UTC'
    const anomalyDetectionEnabled = useFeatureFlag('ALERTS_ANOMALY_DETECTION')
    const inlineNotificationsEnabled = useFeatureFlag('ALERTS_INLINE_NOTIFICATIONS')
    const investigationAgentEnabled = useFeatureFlag('ALERTS_INVESTIGATION_AGENT')

    const { hasAvailableFeature } = useValues(userLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const hasHighFrequencyAlertsEntitlement = hasAvailableFeature(AvailableFeature.HIGH_FREQUENCY_ALERTS)

    const handleClose = useCallback(() => {
        clearSimulation()
        if (insightLogicProps && insightId) {
            insightAlertsLogic({ insightId, insightLogicProps }).actions.clearSimulationAnomalyPoints()
        }
        onClose?.()
    }, [clearSimulation, insightLogicProps, insightId, onClose])

    const clearSimulationOverlay = useCallback(() => {
        if (insightLogicProps && insightId) {
            insightAlertsLogic({ insightId, insightLogicProps }).actions.clearSimulationAnomalyPoints()
        }
    }, [insightLogicProps, insightId])

    const creatingNewAlert = alertForm.id === undefined
    const can_check_ongoing_interval = canCheckOngoingInterval(alertForm, { isTrendsFunnel })
    const alertMode = alertForm.detector_config ? 'detector' : 'threshold'
    const nextPlannedEvaluationStale = useMemo(
        () =>
            isNextPlannedEvaluationStale(
                creatingNewAlert,
                alert
                    ? {
                          calculation_interval: alert.calculation_interval,
                          schedule_restriction: alert.schedule_restriction,
                          skip_weekend: alert.skip_weekend,
                          config: supportsOngoingInterval(alert.config)
                              ? { check_ongoing_interval: alert.config.check_ongoing_interval }
                              : null,
                      }
                    : null,
                {
                    calculation_interval: alertForm.calculation_interval,
                    schedule_restriction: alertForm.schedule_restriction,
                    skip_weekend: alertForm.skip_weekend,
                    config: supportsOngoingInterval(alertForm.config)
                        ? { check_ongoing_interval: alertForm.config.check_ongoing_interval }
                        : null,
                }
            ),
        [
            alert,
            alertForm.calculation_interval,
            alertForm.schedule_restriction,
            alertForm.skip_weekend,
            alertForm.config,
            creatingNewAlert,
        ]
    )

    const enabledAdvancedOptionsCount = useMemo(() => {
        let n = 0
        if (
            supportsOngoingInterval(alertForm.config) &&
            alertForm.config.check_ongoing_interval &&
            can_check_ongoing_interval
        ) {
            n += 1
        }
        if (
            (alertForm.calculation_interval === AlertCalculationInterval.DAILY ||
                isHighFrequencyAlertInterval(alertForm.calculation_interval)) &&
            alertForm.skip_weekend
        ) {
            n += 1
        }
        if ((alertForm.schedule_restriction?.blocked_windows?.length ?? 0) > 0) {
            n += 1
        }
        return n
    }, [
        alertForm.calculation_interval,
        alertForm.config,
        alertForm.schedule_restriction?.blocked_windows?.length,
        alertForm.skip_weekend,
        can_check_ongoing_interval,
    ])

    return (
        <LemonModal onClose={handleClose} isOpen={isOpen} width={900} simple title="">
            {alertLoading && !alert ? (
                <SpinnerOverlay />
            ) : (
                <Form
                    logic={alertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    <LemonModal.Header>
                        <div className="flex items-center gap-2">
                            <LemonButton icon={<IconChevronLeft />} onClick={handleClose} size="xsmall" />

                            <h3>{creatingNewAlert ? 'New' : 'Edit '} Alert</h3>
                        </div>
                    </LemonModal.Header>

                    <LemonModal.Content>
                        <div className="deprecated-space-y-6">
                            <div className="deprecated-space-y-4">
                                <div className="flex gap-4 items-center">
                                    <LemonField className="flex-auto" name="name">
                                        <LemonInput placeholder="Alert name" data-attr="alertForm-name" />
                                    </LemonField>
                                    <LemonField name="enabled">
                                        <LemonCheckbox
                                            checked={alertForm?.enabled}
                                            data-attr="alertForm-enabled"
                                            fullWidth
                                            label="Enabled"
                                        />
                                    </LemonField>
                                </div>
                                {alert?.created_by ? (
                                    <UserActivityIndicator
                                        at={alert.created_at}
                                        by={alert.created_by}
                                        prefix="Created"
                                    />
                                ) : null}
                            </div>

                            <div className="deprecated-space-y-3">
                                <h3 className="mb-0">Definition</h3>
                                <div className="deprecated-space-y-3">
                                    <AlertDefinitionSection
                                        alertForm={alertForm}
                                        alertMode={alertMode}
                                        thresholdBoundsFormError={thresholdBoundsFormError}
                                        isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                                        trends={{ alertSeries, formulaNodes, isBreakdownValid }}
                                        funnel={{
                                            stepLabels: funnelStepLabels,
                                            preview: funnelAlertPreview,
                                            isTrendsFunnel,
                                        }}
                                        hogql={{
                                            preview: hogqlAlertPreview,
                                            columns: hogqlResultColumns,
                                            valueColumnOptions: hogqlValueColumnOptions,
                                            labelColumnOptions: hogqlLabelColumnOptions,
                                        }}
                                        anomalyDetectionEnabled={
                                            anomalyDetectionEnabled && supportsAnomalyDetection(alertForm.config)
                                        }
                                        investigationAgentEnabled={investigationAgentEnabled}
                                        simulationResult={simulationResult}
                                        simulationResultLoading={simulationResultLoading}
                                        simulationDateFrom={simulationDateFrom}
                                        onSetAlertFormValue={setAlertFormValue}
                                        onSimulateAlert={simulateAlert}
                                        onSetSimulationDateFrom={setSimulationDateFrom}
                                        onClearSimulation={clearSimulation}
                                        onClearSimulationOverlay={clearSimulationOverlay}
                                    />
                                    <AlertIntervalRow
                                        alertForm={alertForm}
                                        creatingNewAlert={creatingNewAlert}
                                        alert={alert}
                                        trendInterval={trendInterval}
                                        hasHighFrequencyAlertsEntitlement={hasHighFrequencyAlertsEntitlement}
                                        guardAvailableFeature={guardAvailableFeature}
                                        nextPlannedEvaluationStale={nextPlannedEvaluationStale}
                                    />
                                </div>
                            </div>

                            <div className="text-muted text-sm flex flex-wrap items-start gap-2">
                                <IconCalendar className="size-4 shrink-0 text-muted mt-0.5" aria-hidden />
                                <span className="min-w-0">
                                    Times use your project timezone ({projectTimezone}).{' '}
                                    <Link
                                        to={urls.settings('environment-customization', 'date-and-time')}
                                        target="_blank"
                                        targetBlankIcon={false}
                                    >
                                        Change in settings
                                    </Link>
                                </span>
                            </div>

                            <AlertNotificationSection
                                alertForm={alertForm}
                                alertId={alertId}
                                insightShortId={insightShortId}
                                inlineNotificationsEnabled={inlineNotificationsEnabled}
                                onSetAlertFormValue={setAlertFormValue}
                            />

                            <AlertAdvancedOptionsSection
                                alertForm={alertForm}
                                canCheckOngoingInterval={can_check_ongoing_interval}
                                projectTimezone={projectTimezone}
                                enabledAdvancedOptionsCount={enabledAdvancedOptionsCount}
                                onSetAlertFormValue={setAlertFormValue}
                            />
                        </div>

                        {alertId ? (
                            alert ? (
                                <AlertHistorySection alertId={alert.id} />
                            ) : alertLoading ? (
                                <AlertHistorySectionSkeleton />
                            ) : null
                        ) : null}
                    </LemonModal.Content>

                    <LemonModal.Footer>
                        <div className="flex-1">
                            <div className="flex gap-2">
                                {!creatingNewAlert ? (
                                    <LemonButton type="secondary" status="danger" onClick={deleteAlert}>
                                        Delete alert
                                    </LemonButton>
                                ) : null}
                                {!creatingNewAlert && alert?.state === AlertState.FIRING ? (
                                    <SnoozeButton onChange={snoozeAlert} value={alert?.snoozed_until} />
                                ) : null}
                                {!creatingNewAlert && alert?.state === AlertState.SNOOZED ? (
                                    <LemonButton
                                        type="secondary"
                                        status="default"
                                        onClick={clearSnooze}
                                        tooltip={`Currently snoozed until ${formatDate(
                                            dayjs(alert?.snoozed_until),
                                            'MMM D, HH:mm'
                                        )}`}
                                    >
                                        Clear snooze
                                    </LemonButton>
                                ) : null}
                            </div>
                        </div>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isAlertFormSubmitting}
                            onClick={() => setAlertFormSubmitAttempted()}
                        >
                            {creatingNewAlert ? 'Create alert' : 'Save'}
                        </LemonButton>
                    </LemonModal.Footer>
                </Form>
            )}
        </LemonModal>
    )
}
