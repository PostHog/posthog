import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useMemo } from 'react'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { formatDate } from 'lib/utils/datetime'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getDisplayNameFromEntityNode } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import { AlertCalculationInterval, AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isInsightVizNode } from '~/queries/utils'
import { FunnelVizType, InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { AlertAdvancedOptionsSection } from 'products/alerts/frontend/components/AlertAdvancedOptionsSection'
import { AlertStateIndicator, AlertTimezoneNotice } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertDefinitionSection } from 'products/alerts/frontend/components/AlertDefinitionSection'
import {
    AlertEditor,
    AlertEditorFormDetails,
    AlertEditorLoading,
} from 'products/alerts/frontend/components/AlertEditor'
import { AlertIntervalRow } from 'products/alerts/frontend/components/AlertIntervalRow'
import { AlertPreviewCard } from 'products/alerts/frontend/components/AlertPreviewCard'
import { buildAlertSummary } from 'products/alerts/frontend/components/alertSummary'
import { AlertWizard } from 'products/alerts/frontend/components/AlertWizard'
import { ThresholdConditionRow } from 'products/alerts/frontend/components/ThresholdConditionRow'
import { isSubDailyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { quietHoursFormError } from 'products/alerts/frontend/logic/scheduleRestrictionValidation'
import { deriveAlertCheckPreviewSeries } from 'products/alerts/frontend/logic/trendsAlertPreview'
import { InsightAlertNotificationSection } from 'products/alerts/frontend/views/InsightAlertNotificationSection'

import { alertFormLogic, canCheckOngoingInterval, insightAlertKindForQuery } from '../logic/alertFormLogic'
import { alertLogic } from '../logic/alertLogic'
import { alertNotificationLogic } from '../logic/alertNotificationLogic'
import { isNextPlannedEvaluationStale } from '../logic/alertSchedulingStale'
import { insightAlertsLogic } from '../logic/insightAlertsLogic'
import { supportsAnomalyDetection, supportsOngoingInterval } from '../types'
import type { AlertType } from '../types'
import { AlertHistorySection } from './AlertHistorySection'
import { AlertEnabledAction, AlertLeadingActions } from './EditAlertModal/AlertLeadingActions'
import { AlertNotFoundModal } from './EditAlertModal/AlertNotFoundModal'
import { buildWizardSteps } from './EditAlertModal/buildWizardSteps'
import { defaultAlertTabs, EditAlertTabs } from './EditAlertModal/EditAlertTabs'

interface AlertModalCommonProps {
    isOpen: boolean | undefined
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    defaultToAnomalyDetection?: boolean
    insightName?: string | null
    useAlertCheckPreview?: boolean
}

type AlertModalProps = AlertModalCommonProps &
    (
        | {
              alert: AlertType
              alertId?: never
              insightId?: never
              insightShortId?: never
              insightLogicProps?: never
          }
        | {
              alert?: never
              alertId?: AlertType['id']
              insightId: QueryBasedInsightModel['id']
              insightShortId: InsightShortId
              insightLogicProps: InsightLogicProps
          }
    )

interface ResolvedAlertModalProps extends AlertModalCommonProps {
    initialAlert?: AlertType
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export function EditAlertModal(props: AlertModalProps): JSX.Element {
    const resolvedProps: ResolvedAlertModalProps = props.alert
        ? {
              ...props,
              initialAlert: props.alert,
              alertId: props.alert.id,
              insightId: props.alert.insight.id,
              insightShortId: props.alert.insight.short_id,
              insightLogicProps: {
                  dashboardItemId: props.alert.insight.short_id,
                  cachedInsight: props.alert.insight,
              },
          }
        : props
    const {
        initialAlert,
        isOpen,
        alertId,
        insightId,
        insightShortId,
        onClose,
        onEditSuccess,
        insightLogicProps,
        defaultToAnomalyDetection,
        insightName,
        useAlertCheckPreview,
    } = resolvedProps
    const _alertLogic = alertLogic({ alertId })
    const { alert: loadedAlert, alertLoading } = useValues(_alertLogic)
    const alert = initialAlert ?? loadedAlert
    const { insightLoading } = useValues(insightLogic(insightLogicProps))

    const _onEditSuccess = useCallback(
        (alertId: AlertType['id'] | undefined) => {
            onEditSuccess(alertId)
        },
        [onEditSuccess]
    )

    const trendsLogic = trendsDataLogic(insightLogicProps)
    const {
        alertSeries,
        isNonTimeSeriesDisplay,
        isBreakdownValid,
        formulaNodes,
        interval: trendInterval,
        indexedResults,
        insightDataLoading,
    } = useValues(trendsLogic)

    const { query } = useValues(insightVizDataLogic(insightLogicProps))

    const funnelSource = !!query && isInsightVizNode(query) && isFunnelsQuery(query.source) ? query.source : null
    const isTrendsFunnel = funnelSource?.funnelsFilter?.funnelVizType === FunnelVizType.Trends
    const funnelStepLabels = (funnelSource?.series ?? []).map(
        (node, index) => getDisplayNameFromEntityNode(node) ?? `Step ${index + 1}`
    )
    const insightAlertKind = insightAlertKindForQuery(query)
    const anomalyAlertGuidanceEnabled = useFeatureFlag('ANOMALY_ALERT_GUIDANCE_EXPERIMENT', 'anomaly_guidance')

    const formLogicProps = {
        alert,
        insightId,
        onEditSuccess: _onEditSuccess,
        insightVizDataLogicProps: insightLogicProps,
        insightInterval: trendInterval ?? undefined,
        insightAlertKind,
        defaultToAnomalyDetection: !alertId && !isNonTimeSeriesDisplay && defaultToAnomalyDetection,
        insightName,
        insightIsTrendsFunnel: isTrendsFunnel,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const {
        alertForm,
        isAlertFormSubmitting,
        alertFormChanged,
        alertFormHasErrors,
        alertFormValidationErrors,
        alertFormSubmitAttempted,
        simulationResult,
        simulationResultLoading,
        simulationDateFrom,
        clearSnoozeLoading,
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
    const inlineNotificationsEnabled = useFeatureFlag('ALERTS_INLINE_NOTIFICATIONS')
    const investigationAgentEnabled = useFeatureFlag('ALERTS_INVESTIGATION_AGENT')

    const notificationLogic = alertNotificationLogic({ alertId })
    const { existingHogFunctions, pendingNotifications, testDeliveryResultLoading } = useValues(notificationLogic)
    const { sendTestDelivery } = useActions(notificationLogic)
    const hasPendingNotifications = inlineNotificationsEnabled && pendingNotifications.length > 0
    const hasTestDeliveryTargets =
        (alert?.subscribed_users?.some((user) => Boolean(user.email)) ?? false) ||
        existingHogFunctions.some((hogFunction) => hogFunction.enabled)

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

    const creatingNewAlert = alertId === undefined
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
                isSubDailyAlertInterval(alertForm.calculation_interval)) &&
            alertForm.skip_weekend
        ) {
            n += 1
        }
        return n
    }, [alertForm.calculation_interval, alertForm.config, alertForm.skip_weekend, can_check_ongoing_interval])

    const subscribedCount = alertForm.subscribed_users?.length ?? 0
    const destinationCount = existingHogFunctions.length + pendingNotifications.length
    const summary = useMemo(
        () => buildAlertSummary(alertForm, subscribedCount, destinationCount),
        [alertForm, destinationCount, subscribedCount]
    )

    // The monitored trends series' values, for the live preview sparkline. Picked by the alert's
    // series_index so the preview matches what the alert actually evaluates.
    const trendsPreviewValues = useMemo(() => {
        if (!isTrendsFunnel && alertForm.config?.type === 'TrendsAlertConfig') {
            const idx = alertForm.config.series_index ?? 0
            const series = indexedResults?.[idx]
            return series?.data ?? null
        }
        return null
    }, [alertForm.config, indexedResults, isTrendsFunnel])

    const checkPreview = useMemo(() => {
        if (!useAlertCheckPreview || !alert) {
            return undefined
        }
        const preview = deriveAlertCheckPreviewSeries(
            alert.checks ?? [],
            alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE,
            alertForm.threshold?.configuration?.type ?? InsightThresholdType.ABSOLUTE
        )
        return {
            ...preview,
            labels: preview.labels?.map((label) => formatDate(dayjs(label), 'MMM D, HH:mm')),
        }
    }, [alert, alertForm.condition?.type, alertForm.threshold?.configuration?.type, useAlertCheckPreview])

    const leadingActions = (
        <AlertLeadingActions
            alertForm={alertForm}
            alert={alert}
            onDeleteAlert={deleteAlert}
            onSnoozeAlert={snoozeAlert}
            onClearSnooze={clearSnooze}
            clearSnoozeLoading={clearSnoozeLoading}
            onSendTestDelivery={sendTestDelivery}
            testDeliveryLoading={testDeliveryResultLoading}
            testDeliveryDisabledReason={
                alertFormChanged || hasPendingNotifications ? 'Save changes before testing.' : undefined
            }
            showTestDelivery={hasTestDeliveryTargets}
        />
    )

    const thresholdValidationError =
        typeof alertFormValidationErrors.threshold === 'string' ? alertFormValidationErrors.threshold : undefined

    const definitionNode = (
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
            supportsAnomalyDetection={!isNonTimeSeriesDisplay && supportsAnomalyDetection(alertForm.config)}
            showAnomalyGuidance={creatingNewAlert && anomalyAlertGuidanceEnabled}
            twoColumnLayout
            investigationAgentEnabled={investigationAgentEnabled}
            simulationResult={simulationResult}
            simulationResultLoading={simulationResultLoading}
            simulationDateFrom={simulationDateFrom}
            onSetAlertFormValue={setAlertFormValue}
            thresholdRowRenderer={(props) => <ThresholdConditionRow {...props} />}
            onSimulateAlert={simulateAlert}
            onSetSimulationDateFrom={setSimulationDateFrom}
            onClearSimulation={clearSimulation}
            onClearSimulationOverlay={clearSimulationOverlay}
        />
    )

    const scheduleNode = (
        <div className="space-y-2">
            <AlertIntervalRow
                alertForm={alertForm}
                creatingNewAlert={creatingNewAlert}
                alert={alert}
                trendInterval={trendInterval}
                nextPlannedEvaluationStale={nextPlannedEvaluationStale}
                canCheckOngoingInterval={can_check_ongoing_interval}
                onSetAlertFormValue={setAlertFormValue}
            />
            <AlertTimezoneNotice
                timezone={projectTimezone}
                settingsUrl={urls.settings('environment-customization', 'date-and-time')}
            />
        </div>
    )

    const notifyNode = (
        <InsightAlertNotificationSection
            alertForm={alertForm}
            alertId={alertId}
            insightShortId={insightShortId}
            inlineNotificationsEnabled={inlineNotificationsEnabled}
            showSectionTitle={false}
            onSetAlertFormValue={setAlertFormValue}
        />
    )

    const advancedNode = (
        <AlertAdvancedOptionsSection
            alertForm={alertForm}
            canCheckOngoingInterval={can_check_ongoing_interval}
            projectTimezone={projectTimezone}
            enabledAdvancedOptionsCount={enabledAdvancedOptionsCount}
            defaultOpen
            onSetAlertFormValue={setAlertFormValue}
        />
    )

    const previewNode = (
        <AlertPreviewCard
            alertForm={alertForm}
            trendsValues={trendsPreviewValues}
            trendsLabels={
                indexedResults?.[
                    alertForm.config?.type === 'TrendsAlertConfig' ? (alertForm.config.series_index ?? 0) : 0
                ]?.labels ?? null
            }
            funnelPreview={funnelAlertPreview}
            hogqlPreview={hogqlAlertPreview}
            checkPreview={checkPreview}
            loading={!useAlertCheckPreview && (insightLoading || insightDataLoading)}
        />
    )
    const nameError = alertFormSubmitAttempted && !alertForm.name ? 'Enter an alert name.' : undefined
    const scheduleRestrictionFormError = quietHoursFormError(alertForm.schedule_restriction)

    if (alertId && !alertLoading && !alert) {
        return <AlertNotFoundModal isOpen={Boolean(isOpen)} onClose={handleClose} />
    }

    return (
        <LemonModal onClose={handleClose} isOpen={isOpen} width={900} simple title="">
            {alertLoading && !alert ? (
                <AlertEditorLoading title="Edit alert" onBack={handleClose} />
            ) : (
                <Form
                    logic={alertFormLogic}
                    props={formLogicProps}
                    formKey="alertForm"
                    enableFormOnSubmit
                    className="LemonModal__layout"
                >
                    {creatingNewAlert ? (
                        <AlertWizard
                            title="New alert"
                            isSubmitting={isAlertFormSubmitting}
                            hasChanges={alertFormChanged}
                            onBack={handleClose}
                            onSubmitAttempted={setAlertFormSubmitAttempted}
                            steps={buildWizardSteps({
                                nameNode: <AlertEditorFormDetails nameError={nameError} />,
                                definitionNode,
                                previewNode,
                                scheduleNode,
                                notifyNode,
                                advancedNode,
                                summary,
                                thresholdValidationError,
                                scheduleRestrictionFormError,
                                alertFormHasErrors,
                                alertName: alertForm.name,
                            })}
                        />
                    ) : (
                        <AlertEditor
                            title="Edit alert"
                            className="min-h-0 flex-1 overflow-hidden"
                            contentClassName="min-h-0 flex-1 overflow-y-auto"
                            onBack={handleClose}
                            isEditing
                            isSubmitting={isAlertFormSubmitting}
                            hasChanges={alertFormChanged}
                            hasPendingChanges={hasPendingNotifications}
                            onSubmitAttempted={setAlertFormSubmitAttempted}
                            leadingActions={leadingActions}
                            trailingActions={<AlertEnabledAction alertForm={alertForm} />}
                        >
                            <div className="space-y-3">
                                {(() => {
                                    const tabs = defaultAlertTabs({
                                        monitorContent: (
                                            <div className="space-y-3 pt-3">
                                                <AlertEditorFormDetails
                                                    nameError={nameError}
                                                    activity={
                                                        alert?.created_by ? (
                                                            <UserActivityIndicator
                                                                at={alert.created_at}
                                                                by={alert.created_by}
                                                                prefix="Created"
                                                            />
                                                        ) : undefined
                                                    }
                                                />
                                                {previewNode}
                                                {definitionNode}
                                            </div>
                                        ),
                                        scheduleContent: (
                                            <div className="space-y-3 pt-3">
                                                {scheduleNode}
                                                {advancedNode}
                                            </div>
                                        ),
                                        notifyContent: <div className="pt-3">{notifyNode}</div>,
                                        historyContent:
                                            alertId && alert ? (
                                                <div className="pt-3">
                                                    <AlertHistorySection alertId={alert.id} showCurrentStatus={false} />
                                                </div>
                                            ) : undefined,
                                    })
                                    return (
                                        <EditAlertTabs
                                            summary={summary}
                                            summaryHeader={
                                                alert ? (
                                                    <div className="flex items-center justify-between gap-3">
                                                        <span className="font-medium">Current status</span>
                                                        <AlertStateIndicator alert={alert} />
                                                    </div>
                                                ) : undefined
                                            }
                                            tabs={tabs}
                                        />
                                    )
                                })()}
                            </div>
                        </AlertEditor>
                    )}
                </Form>
            )}
        </LemonModal>
    )
}
