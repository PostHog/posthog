import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useCallback, useMemo, useState } from 'react'

import { IconBell, IconClock, IconGraph, IconPulse } from '@posthog/icons'
import { LemonDialog, LemonTabs } from '@posthog/lemon-ui'
import type { LemonTab } from '@posthog/lemon-ui'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { formatDate } from 'lib/utils/datetime'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getDisplayNameFromEntityNode } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { urls } from 'scenes/urls'

import {
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import { isFunnelsQuery, isInsightVizNode } from '~/queries/utils'
import { FunnelVizType } from '~/types'

import { AlertAdvancedOptionsSection } from 'products/alerts/frontend/components/AlertAdvancedOptionsSection'
import { AlertTimezoneNotice } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertDefinitionSection } from 'products/alerts/frontend/components/AlertDefinitionSection'
import {
    AlertEditor,
    AlertEditorFormDetails,
    AlertEditorLoading,
} from 'products/alerts/frontend/components/AlertEditor'
import { AlertIntervalRow } from 'products/alerts/frontend/components/AlertIntervalRow'
import { AlertPreviewCard } from 'products/alerts/frontend/components/AlertPreviewCard'
import { AlertStateIndicator } from 'products/alerts/frontend/components/AlertStateIndicator'
import { buildAlertSummary } from 'products/alerts/frontend/components/alertSummary'
import { AlertSummaryBanner, AlertSummarySection } from 'products/alerts/frontend/components/AlertSummaryBanner'
import { AlertWizard, AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'
import { ThresholdConditionRow } from 'products/alerts/frontend/components/ThresholdConditionRow'
import { isSubDailyAlertInterval } from 'products/alerts/frontend/logic/alertIntervalHelpers'
import { deriveAlertCheckPreviewSeries } from 'products/alerts/frontend/logic/trendsAlertPreview'
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
import type { AlertModalProps } from './EditAlertModal'

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
    useAlertCheckPreview,
}: AlertModalProps): JSX.Element {
    const _alertLogic = alertLogic({ alertId })
    const { alert, alertLoading } = useValues(_alertLogic)
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
        uiVersion: 'redesigned' as const,
    }
    const formLogic = alertFormLogic(formLogicProps)
    const {
        alertForm,
        isAlertFormSubmitting,
        alertFormChanged,
        alertFormHasErrors,
        alertFormSubmitAttempted,
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

    const { existingHogFunctions, pendingNotifications } = useValues(alertNotificationLogic({ alertId: alertId }))
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
            alert.checks,
            alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE,
            alertForm.threshold?.configuration?.type ?? InsightThresholdType.ABSOLUTE
        )
        return {
            ...preview,
            labels: preview.labels?.map((label) => formatDate(dayjs(label), 'MMM D, HH:mm')),
        }
    }, [alert, alertForm.condition?.type, alertForm.threshold?.configuration?.type, useAlertCheckPreview])

    const enabledToggle = (
        <LemonField name="enabled" className="m-0">
            <LemonSwitch checked={alertForm.enabled} data-attr="alertForm-enabled" label="Enabled" />
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
                                thresholdBoundsFormError,
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
                        >
                            <div className="space-y-3">
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
                                    nameNode={
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
                                    }
                                    previewNode={previewNode}
                                    definitionNode={definitionNode}
                                    scheduleNode={scheduleNode}
                                    advancedNode={advancedNode}
                                    notifyNode={notifyNode}
                                    historyNode={
                                        alertId && alert ? (
                                            <AlertHistorySection alertId={alert.id} showCurrentStatus={false} />
                                        ) : null
                                    }
                                />
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
    alertFormHasErrors: boolean
    alertName: string
}

function buildWizardSteps(input: WizardStepInput): AlertWizardStep[] {
    const { summary, alertFormHasErrors } = input
    const reviewFires = summary.fires || 'a configured threshold'
    const reviewCadence = summary.cadence || 'a cadence'
    const reviewNotifies = summary.notifies || 'no one yet'
    const monitorCannotAdvanceReason = !input.alertName
        ? 'Enter an alert name.'
        : input.thresholdBoundsFormError || 'Fix the errors above before continuing.'

    return [
        {
            key: 'monitor',
            title: 'Monitor',
            description: 'Pick what this alert watches and when it should fire.',
            canAdvance: !alertFormHasErrors,
            cannotAdvanceReason: alertFormHasErrors ? monitorCannotAdvanceReason : undefined,
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
            canAdvance: true,
            content: (
                <div className="space-y-3">
                    {input.scheduleNode}
                    {input.advancedNode}
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Who gets told when this alert fires.',
            canAdvance: true,
            content: <div className="space-y-4">{input.notifyNode}</div>,
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm what this alert will do, then create it.',
            canAdvance: !alertFormHasErrors,
            cannotAdvanceReason: alertFormHasErrors ? 'Fix the errors in previous steps before creating.' : undefined,
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

interface EditAlertTabsProps {
    summary: { fires: string; cadence: string; notifies: string }
    summaryHeader?: React.ReactNode
    nameNode: React.ReactNode
    previewNode: React.ReactNode
    definitionNode: React.ReactNode
    scheduleNode: React.ReactNode
    advancedNode: React.ReactNode
    notifyNode: React.ReactNode
    historyNode: React.ReactNode | null
}

function EditAlertTabs({
    summary,
    summaryHeader,
    nameNode,
    previewNode,
    definitionNode,
    scheduleNode,
    advancedNode,
    notifyNode,
    historyNode,
}: EditAlertTabsProps): JSX.Element {
    const [activeKey, setActiveKey] = useState<string>('monitor')

    const tabs: (LemonTab<string> | null)[] = [
        {
            key: 'monitor',
            label: (
                <span className="flex items-center gap-1.5">
                    <IconPulse className="size-4" />
                    Monitor
                </span>
            ),
            content: (
                <div className="space-y-3 pt-3">
                    {nameNode}
                    {previewNode}
                    {definitionNode}
                </div>
            ),
        },
        {
            key: 'schedule',
            label: (
                <span className="flex items-center gap-1.5">
                    <IconClock className="size-4" />
                    Schedule
                </span>
            ),
            content: (
                <div className="space-y-3 pt-3">
                    {scheduleNode}
                    {advancedNode}
                </div>
            ),
        },
        {
            key: 'notify',
            label: (
                <span className="flex items-center gap-1.5">
                    <IconBell className="size-4" />
                    Notify
                </span>
            ),
            content: <div className="pt-3">{notifyNode}</div>,
        },
        historyNode
            ? {
                  key: 'history',
                  label: (
                      <span className="flex items-center gap-1.5">
                          <IconGraph className="size-4" />
                          History
                      </span>
                  ),
                  content: <div className="pt-3">{historyNode}</div>,
              }
            : null,
    ]

    let activeSummarySection: AlertSummarySection | undefined
    if (activeKey === 'monitor' || activeKey === 'schedule' || activeKey === 'notify') {
        activeSummarySection = activeKey
    }

    return (
        <div className="space-y-3">
            <AlertSummaryBanner summary={summary} header={summaryHeader} activeSection={activeSummarySection} />
            <LemonTabs tabs={tabs} activeKey={activeKey} onChange={setActiveKey} className="flex-1 min-h-0" />
        </div>
    )
}
