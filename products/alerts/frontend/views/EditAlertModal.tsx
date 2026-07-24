import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useMemo } from 'react'

import { LemonDialog, LemonSwitch } from '@posthog/lemon-ui'

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

import { AlertCalculationInterval, AlertState } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isInsightVizNode } from '~/queries/utils'
import { FunnelVizType, InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { AlertAdvancedOptionsSection } from 'products/alerts/frontend/components/AlertAdvancedOptionsSection'
import { AlertTimezoneNotice } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertDefinitionSection } from 'products/alerts/frontend/components/AlertDefinitionSection'
import {
    AlertEditor,
    AlertEditorFormDetails,
    AlertEditorLoading,
    AlertEditorSection,
} from 'products/alerts/frontend/components/AlertEditor'
import { AlertIntervalRow } from 'products/alerts/frontend/components/AlertIntervalRow'
import { isSubDailyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { InsightAlertNotificationSection } from 'products/alerts/frontend/views/InsightAlertNotificationSection'

import { SnoozeButton } from '../components/SnoozeButton'
import { alertFormLogic, canCheckOngoingInterval, insightAlertKindForQuery } from '../logic/alertFormLogic'
import { alertLogic } from '../logic/alertLogic'
import { alertNotificationLogic } from '../logic/alertNotificationLogic'
import { isNextPlannedEvaluationStale } from '../logic/alertSchedulingStale'
import { insightAlertsLogic } from '../logic/insightAlertsLogic'
import { supportsAnomalyDetection, supportsOngoingInterval } from '../types'
import type { AlertType } from '../types'
import { AlertHistorySection } from './AlertHistorySection'
import { EditAlertModalV2 } from './EditAlertModalV2'

interface AlertModalCommonProps {
    isOpen: boolean | undefined
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    defaultToAnomalyDetection?: boolean
    insightName?: string | null
    useAlertCheckPreview?: boolean
}

export type AlertModalProps = AlertModalCommonProps &
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

export interface ResolvedAlertModalProps extends AlertModalCommonProps {
    initialAlert?: AlertType
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export function EditAlertModal(props: AlertModalProps): JSX.Element {
    // Redesigned modal (wizard for new alerts, sectioned layout + live preview for edits). The flag
    // is the single switch: off = legacy modal below, on = V2. Consumers don't change.
    const redesigned = useFeatureFlag('ALERTS_REDESIGNED_EDIT_MODAL')
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
    if (redesigned) {
        return <EditAlertModalV2 {...resolvedProps} />
    }
    return <LegacyEditAlertModal {...resolvedProps} />
}

function LegacyEditAlertModal({
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
}: ResolvedAlertModalProps): JSX.Element {
    const _alertLogic = alertLogic({ alertId })
    const { alert: loadedAlert, alertLoading } = useValues(_alertLogic)
    const alert = initialAlert ?? loadedAlert

    /** Parent callback only (e.g. close modal). `alertLogic` is hydrated from the save response inside `alertFormLogic`. */
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
    } = useValues(trendsLogic)

    const { query } = useValues(insightVizDataLogic(insightLogicProps))

    const funnelSource = !!query && isInsightVizNode(query) && isFunnelsQuery(query.source) ? query.source : null
    // Trends funnels alert on the overall conversion rate over time, so they skip the step picker and
    // the preview reads the latest period instead of a step snapshot. The backend dispatches on the
    // same viz type — see funnel_strategies.py.
    const isTrendsFunnel = funnelSource?.funnelsFilter?.funnelVizType === FunnelVizType.Trends
    const funnelStepLabels = (funnelSource?.series ?? []).map(
        (node, index) => getDisplayNameFromEntityNode(node) ?? `Step ${index + 1}`
    )
    const insightAlertKind = insightAlertKindForQuery(query)

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
        uiVersion: 'legacy' as const,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const {
        alertForm,
        isAlertFormSubmitting,
        alertFormChanged,
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
    const inlineNotificationsEnabled = useFeatureFlag('ALERTS_INLINE_NOTIFICATIONS')
    const investigationAgentEnabled = useFeatureFlag('ALERTS_INVESTIGATION_AGENT')

    const { pendingNotifications } = useValues(alertNotificationLogic({ alertId: alertId }))
    const hasPendingNotifications = inlineNotificationsEnabled && pendingNotifications.length > 0

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
                isSubDailyAlertInterval(alertForm.calculation_interval)) &&
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

    const leadingActions = (
        <div className="flex items-center gap-2">
            {!creatingNewAlert ? (
                <LemonButton
                    type="secondary"
                    status="danger"
                    onClick={() => {
                        LemonDialog.open({
                            title: `Delete "${alertForm.name || 'this alert'}"?`,
                            description: 'This alert will be permanently deleted. This action cannot be undone.',
                            primaryButton: {
                                children: 'Delete',
                                type: 'primary',
                                status: 'danger',
                                onClick: deleteAlert,
                                'data-attr': 'alert-delete-confirm',
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Delete alert
                </LemonButton>
            ) : null}
            {!creatingNewAlert ? (
                <SnoozeButton
                    onChange={snoozeAlert}
                    value={alert?.snoozed_until}
                    disabledReason={
                        alert?.state === AlertState.FIRING ? undefined : 'Only firing alerts can be snoozed'
                    }
                />
            ) : null}
            {!creatingNewAlert && alert?.state === AlertState.SNOOZED ? (
                <LemonButton
                    type="secondary"
                    status="default"
                    onClick={clearSnooze}
                    tooltip={`Currently snoozed until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}
                >
                    Clear snooze
                </LemonButton>
            ) : null}
            <div className="ml-auto mr-2">
                <LemonField name="enabled" className="m-0">
                    <LemonSwitch checked={alertForm.enabled} data-attr="alertForm-enabled" label="Enabled" />
                </LemonField>
            </div>
        </div>
    )

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
                    <AlertEditor
                        title={creatingNewAlert ? 'New alert' : 'Edit alert'}
                        className="min-h-0 flex-1 overflow-hidden"
                        contentClassName="min-h-0 flex-1 overflow-y-auto"
                        onBack={handleClose}
                        isEditing={!creatingNewAlert}
                        isSubmitting={isAlertFormSubmitting}
                        hasChanges={alertFormChanged}
                        hasPendingChanges={hasPendingNotifications}
                        showNoChangesLabel
                        onSubmitAttempted={setAlertFormSubmitAttempted}
                        leadingActions={leadingActions}
                    >
                        <div className="deprecated-space-y-6">
                            <AlertEditorFormDetails
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

                            <AlertEditorSection title="Definition">
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
                                        supportsAnomalyDetection={
                                            !isNonTimeSeriesDisplay && supportsAnomalyDetection(alertForm.config)
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
                                        nextPlannedEvaluationStale={nextPlannedEvaluationStale}
                                        canCheckOngoingInterval={can_check_ongoing_interval}
                                        projectTimezone={projectTimezone}
                                        onSetAlertFormValue={setAlertFormValue}
                                    />
                                </div>
                            </AlertEditorSection>

                            <AlertTimezoneNotice
                                timezone={projectTimezone}
                                settingsUrl={urls.settings('environment-customization', 'date-and-time')}
                            />

                            <InsightAlertNotificationSection
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

                        {alertId && alert ? (
                            <div className="mt-6">
                                <AlertHistorySection alertId={alert.id} />
                            </div>
                        ) : null}
                    </AlertEditor>
                </Form>
            )}
        </LemonModal>
    )
}
