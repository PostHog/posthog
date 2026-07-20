import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useMemo } from 'react'

import { LemonCheckbox, LemonDialog, SpinnerOverlay } from '@posthog/lemon-ui'

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
    AlertEditorSection,
} from 'products/alerts/frontend/components/AlertEditor'
import { AlertIntervalRow } from 'products/alerts/frontend/components/AlertIntervalRow'
import { AlertPreviewCard } from 'products/alerts/frontend/components/AlertPreviewCard'
import { buildAlertSummary } from 'products/alerts/frontend/components/alertSummary'
import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'
import { ThresholdConditionRow } from 'products/alerts/frontend/components/ThresholdConditionRow'
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

interface EditAlertModalV2Props {
    isOpen: boolean | undefined
    alertId?: AlertType['id']
    insightId: QueryBasedInsightModel['id']
    insightShortId: InsightShortId
    onEditSuccess: (alertId?: AlertType['id'] | undefined) => void
    onClose?: () => void
    insightLogicProps: InsightLogicProps
    defaultToAnomalyDetection?: boolean
    insightName?: string | null
}

/** Redesigned alert edit/create modal. New alerts use a 3-step wizard (Monitor → Schedule & notify
 *  → Review); editing an existing alert skips the wizard and uses a sectioned layout with a one-line
 *  summary and a live preview card. Gated behind the ALERTS_REDESIGNED_EDIT_MODAL feature flag. */
export function EditAlertModalV2({
    isOpen,
    alertId,
    insightId,
    insightShortId,
    onClose,
    onEditSuccess,
    insightLogicProps,
    defaultToAnomalyDetection,
    insightName,
}: EditAlertModalV2Props): JSX.Element {
    const _alertLogic = alertLogic({ alertId })
    const { alert, alertLoading } = useValues(_alertLogic)

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
    } = useValues(trendsLogic)

    const { query } = useValues(insightVizDataLogic(insightLogicProps))

    const funnelSource = !!query && isInsightVizNode(query) && isFunnelsQuery(query.source) ? query.source : null
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

    const subscribedCount = alertForm.subscribed_users?.length ?? 0
    const summary = useMemo(() => buildAlertSummary(alertForm, subscribedCount), [alertForm, subscribedCount])

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

    const enabledToggle = (
        <LemonField name="enabled" className="m-0">
            <LemonCheckbox checked={alertForm.enabled} data-attr="alertForm-enabled" label="Enabled" />
        </LemonField>
    )

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
                        })
                    }}
                >
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
                    tooltip={`Currently snoozed until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}
                >
                    Clear snooze
                </LemonButton>
            ) : null}
            <div className="ml-auto">{enabledToggle}</div>
        </div>
    )

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
            onSetAlertFormValue={setAlertFormValue}
        />
    )

    const advancedNode = (
        <AlertAdvancedOptionsSection
            alertForm={alertForm}
            canCheckOngoingInterval={can_check_ongoing_interval}
            projectTimezone={projectTimezone}
            enabledAdvancedOptionsCount={enabledAdvancedOptionsCount}
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
        />
    )

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
                    {creatingNewAlert ? (
                        <AlertWizard
                            title="New alert"
                            isSubmitting={isAlertFormSubmitting}
                            hasChanges={alertFormChanged}
                            onBack={handleClose}
                            onSubmitAttempted={setAlertFormSubmitAttempted}
                            steps={buildWizardSteps({
                                nameNode: (
                                    <AlertEditorFormDetails
                                        enabled={{ checked: alertForm.enabled, dataAttr: 'alertForm-enabled' }}
                                    />
                                ),
                                definitionNode,
                                previewNode,
                                scheduleNode,
                                notifyNode,
                                advancedNode,
                                summary,
                                thresholdBoundsFormError,
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
                        >
                            <div className="space-y-2.5">
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

                                <SummaryBanner summary={summary} alertMode={alertMode} />

                                <div className="rounded border border-border p-3">
                                    <AlertEditorSection title="Monitor">
                                        <div className="space-y-3">
                                            {previewNode}
                                            {definitionNode}
                                        </div>
                                    </AlertEditorSection>
                                </div>

                                <div className="rounded border border-border p-3">
                                    <AlertEditorSection title="Schedule">{scheduleNode}</AlertEditorSection>
                                </div>

                                <div className="rounded border border-border p-3">{notifyNode}</div>

                                <div className="rounded border border-border p-3">{advancedNode}</div>

                                {alertId && alert ? (
                                    <div className="rounded border border-border p-3">
                                        <AlertHistorySection alertId={alert.id} />
                                    </div>
                                ) : null}
                            </div>
                        </AlertEditor>
                    )}
                </Form>
            )}
        </LemonModal>
    )
}

interface WizardStepInput {
    nameNode: React.ReactNode
    definitionNode: React.ReactNode
    previewNode: React.ReactNode
    scheduleNode: React.ReactNode
    notifyNode: React.ReactNode
    advancedNode: React.ReactNode
    summary: { fires: string; cadence: string; notifies: string }
    thresholdBoundsFormError?: string
}

function buildWizardSteps(input: WizardStepInput): AlertWizardStep[] {
    const { summary } = input
    const reviewFires = summary.fires || 'a configured threshold'
    const reviewCadence = summary.cadence || 'a cadence'
    const reviewNotifies = summary.notifies || 'no one yet'

    return [
        {
            key: 'monitor',
            title: 'Monitor',
            description: 'Pick what this alert watches and when it should fire.',
            content: (
                <div className="space-y-4">
                    {input.nameNode}
                    {input.previewNode}
                    {input.definitionNode}
                </div>
            ),
        },
        {
            key: 'schedule',
            title: 'Schedule',
            description: 'How often this alert runs.',
            content: <div className="space-y-3">{input.scheduleNode}</div>,
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Who gets told when this alert fires.',
            content: (
                <div className="space-y-4">
                    {input.notifyNode}
                    {input.advancedNode}
                </div>
            ),
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm what this alert will do, then create it.',
            canAdvance: true,
            content: (
                <div className="space-y-3">
                    <div className="rounded border border-border bg-bg-light p-3 space-y-1.5 text-sm">
                        <div className="flex gap-2">
                            <span className="text-muted w-20 shrink-0">Fires when</span>
                            <span className="font-medium">{reviewFires}</span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-muted w-20 shrink-0">Runs</span>
                            <span className="font-medium">{reviewCadence}</span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-muted w-20 shrink-0">Notifies</span>
                            <span className="font-medium">{reviewNotifies}</span>
                        </div>
                    </div>
                    <p className="text-xs text-muted">
                        You can adjust any of this later without stepping through the wizard — editing an existing alert
                        opens straight to its sections.
                    </p>
                </div>
            ),
        },
    ]
}

function SummaryBanner({
    summary,
    alertMode,
}: {
    summary: { fires: string; cadence: string; notifies: string }
    alertMode: 'detector' | 'threshold'
}): JSX.Element {
    const fires = summary.fires || (alertMode === 'detector' ? 'an anomaly' : 'a threshold')
    const cadence = summary.cadence || 'unscheduled'
    const notifies = summary.notifies || 'no one'
    return (
        <div className="rounded border border-border bg-bg-light px-3 py-2 text-sm flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-muted">Fires when</span>
            <span className="font-medium">{fires}</span>
            <span className="text-border">·</span>
            <span className="text-muted">runs</span>
            <span className="font-medium">{cadence}</span>
            <span className="text-border">·</span>
            <span className="text-muted">notifies</span>
            <span className="font-medium">{notifies}</span>
        </div>
    )
}
