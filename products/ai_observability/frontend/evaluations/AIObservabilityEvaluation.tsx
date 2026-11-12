import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { accessLevelSatisfied, toAccessControlLevel } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { urls } from '~/scenes/urls'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { TraceDrawerHost } from '../redesign/trace/TraceDrawerHost'
import { withoutTraceDrawerParams } from '../redesign/trace/traceDrawerRows'
import { providerKeyStateIssueDescription, providerLabel } from '../settings/providerKeyStateUtils'
import { EvaluationBackfillsTab } from './components/EvaluationBackfillsTab'
import { EvaluationFirstResultStatus } from './components/EvaluationFirstResultStatus'
import { EvaluationLatestReport } from './components/EvaluationLatestReport'
import { EvaluationReportDrawer } from './components/EvaluationReportDrawer'
import { EvaluationReportsCallout } from './components/EvaluationReportsCallout'
import { EvaluationReportsTab } from './components/EvaluationReportsTab'
import { EvaluationRunsTable } from './components/EvaluationRunsTable'
import { EvaluationSceneHeader } from './components/EvaluationSceneHeader'
import {
    formatNumericEvaluationScore,
    booleanOutputConfigError,
    numericOutputConfigError,
    categoricalOutputConfigError,
} from './constants'
import { EvaluationConfigurationForm } from './create/EvaluationConfigurationForm'
import { EvaluationCreatePage } from './create/EvaluationCreatePage'
import {
    evaluationSupportsReportHistory,
    evaluationSupportsReports,
    evaluationSupportsRunOutcomes,
    evaluationTypeUsesModelConfiguration,
} from './evaluationCapabilities'
import { evaluationReportDrawerLogic } from './evaluationReportDrawerLogic'
import { evaluationReportLogic } from './evaluationReportLogic'
import { LLMEvaluationLogicProps, hasUnsetConditionRollout, llmEvaluationLogic } from './llmEvaluationLogic'
import { EvaluationDetailResults } from './overview/EvaluationDetailResults'
import { statusReasonLabel, statusReasonRecoveryLabel } from './statusDisplay'

const RUNS_BACKFILL_TIME_FORMAT = { formatDate: 'MMM D, YYYY', formatTime: 'HH:mm' }

export function AIObservabilityEvaluation(): JSX.Element {
    const {
        evaluation,
        originalEvaluation,
        isReportableEvaluation,
        evaluationBackTarget,
        evaluationLoading,
        evaluationFormSubmitting,
        hasUnsavedChanges,
        formValid,
        isNewEvaluation,
        runsSummary,
        runsBackfillId,
        runsBackfill,
        runsDateRange,
        evaluationProviderKeyIssue,
        activeTab,
        modelSelectionRequired,
        numericBoundsRequired,
        usesDecisionModel,
    } = useValues(llmEvaluationLogic)
    const { searchParams } = useValues(router)
    const { isConfigDirty: reportConfigDirty } = useValues(
        evaluationReportLogic({ evaluationId: isNewEvaluation || !evaluation?.id ? 'new' : evaluation.id })
    )
    // The step layout edits reports with the rest of the configuration, so a report-only edit is unsaved too.
    const unsaved = hasUnsavedChanges || (!isNewEvaluation && reportConfigDirty)
    const { saveEvaluation, resetEvaluation, setActiveTab, setFormStep, setRunsDates } = useActions(llmEvaluationLogic)
    const { push } = useActions(router)
    const settingsUrl = combineUrl(urls.aiObservabilityEvaluations(), {
        ...withoutTraceDrawerParams(searchParams),
        tab: 'settings',
    }).url

    useAttachedContext(
        evaluation ? [{ type: 'evaluation', key: evaluation.id || 'new', label: evaluation.name ?? undefined }] : null
    )

    if (evaluationLoading) {
        return <LemonSkeleton className="w-full h-96" />
    }

    if (!evaluation) {
        return <NotFound object="evaluation" />
    }
    if (isNewEvaluation) {
        return (
            <EvaluationCreatePage
                templateKey={typeof searchParams.template === 'string' ? searchParams.template : undefined}
            />
        )
    }
    const openInPlaygroundUrl =
        evaluationTypeUsesModelConfiguration(evaluation.evaluation_type) && evaluation.id && !usesDecisionModel
            ? combineUrl(urls.aiObservabilityPlayground(), { source_evaluation_id: evaluation.id }).url
            : null

    const isHog = evaluation.evaluation_type === 'hog'
    const isSentiment = evaluation.evaluation_type === 'sentiment'
    const supportsRunOutcomes = evaluationSupportsRunOutcomes(originalEvaluation)

    const configValid = isHog
        ? evaluation.evaluation_config.source.trim().length > 0
        : isSentiment
          ? true
          : evaluation.evaluation_config.prompt.trim().length > 0
    const hasSelectedJudgeModel = !modelSelectionRequired || Boolean(evaluation.model_configuration?.model.trim())
    const hasName = evaluation.name.length > 0
    const basicFieldsValid = hasName && configValid
    const percentageUnset = hasUnsetConditionRollout(evaluation.conditions)
    const percentageOutOfRange = evaluation.conditions.some(
        (c) => (c.rollout_percentage ?? 0) > 100 || (c.rollout_percentage ?? 0) < 0
    )
    const hasConditions = evaluation.conditions.length > 0
    // The save writes the evaluation configuration and then returns to the evaluations list. Runs
    // edits nothing, and Backfills holds a setup this save does not carry, plus its own Start
    // button, so leaving the page from either tab only does what the user did not ask for.
    const showSaveAction = activeTab !== 'runs' && activeTab !== 'backfills'
    const saveButtonDisabledReason = !hasName
        ? 'Add a name for this evaluation'
        : !configValid
          ? isHog
              ? 'Add evaluation code before saving'
              : 'Add an evaluation prompt before saving'
          : !hasSelectedJudgeModel
            ? 'Select a judge model before saving'
            : evaluation.output_type === 'categorical'
              ? (categoricalOutputConfigError(evaluation.output_config) ?? undefined)
              : evaluation.output_type === 'numeric'
                ? (numericOutputConfigError(evaluation.output_config, numericBoundsRequired) ?? undefined)
                : (booleanOutputConfigError(evaluation.output_config) ?? undefined)

    const focusTriggers = (): void => {
        setActiveTab('configuration')
        setFormStep('traffic')
    }

    const handleSave = (): void => {
        if (basicFieldsValid && percentageUnset) {
            focusTriggers()
            lemonToast.warning('Set a sampling percentage between 0.1% and 100% for every condition set before saving.')
            return
        }

        if (!formValid) {
            if (!hasConditions) {
                lemonToast.error('Add at least one condition set before saving.')
            } else if (percentageOutOfRange) {
                lemonToast.error('Sampling percentage must be between 0.1% and 100%.')
            } else {
                lemonToast.error('Some required fields are missing. Please review the configuration.')
            }
            focusTriggers()
            return
        }

        const reportLogic = evaluationReportLogic({ evaluationId: evaluation.id })
        if (evaluationSupportsReports(evaluation) && reportLogic.isMounted() && reportLogic.values.configError) {
            lemonToast.error(reportLogic.values.configError)
            return
        }

        saveEvaluation()
    }

    const handleCancel = (): void => {
        if (unsaved) {
            resetEvaluation()
        }
        push(evaluationBackTarget.path)
    }

    return (
        <div className="@container/evaluation min-w-0 space-y-6 pb-8">
            <EvaluationSceneHeader
                playgroundUrl={openInPlaygroundUrl}
                unsaved={unsaved}
                showSaveAction={showSaveAction}
                saveDisabledReason={saveButtonDisabledReason}
                onSave={handleSave}
                onCancel={handleCancel}
            />

            {evaluation.status === 'error' && (
                <LemonBanner type="error">
                    <div className="space-y-1">
                        <p className="font-semibold">This evaluation was automatically disabled</p>
                        <p>
                            {statusReasonLabel(evaluation.status_reason)}.{' '}
                            {statusReasonRecoveryLabel(evaluation.status_reason)}
                        </p>
                        {evaluation.status_reason_detail && (
                            <div className="space-y-1">
                                <p className="font-semibold">Error details</p>
                                <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border bg-bg-light p-2 font-mono text-xs">
                                    {evaluation.status_reason_detail}
                                </pre>
                            </div>
                        )}
                    </div>
                </LemonBanner>
            )}

            {evaluationProviderKeyIssue && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <p>
                            This evaluation is paused because API key{' '}
                            <span className="font-semibold">{evaluationProviderKeyIssue.name}</span> (
                            {providerLabel(evaluationProviderKeyIssue.provider)}){' '}
                            {providerKeyStateIssueDescription(evaluationProviderKeyIssue.state)}.
                        </p>
                        <p>Error: {evaluationProviderKeyIssue.error_message || 'Unknown error'}</p>
                        <Link to={settingsUrl}>Go to settings to fix this key.</Link>
                    </div>
                </LemonBanner>
            )}

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key)}
                data-attr="llma-evaluation-tabs"
                tabs={[
                    {
                        key: 'runs',
                        label: 'Runs',
                        'data-attr': 'llma-evaluation-runs-tab',
                        content: (
                            <div className="max-w-6xl">
                                <div className="flex flex-wrap gap-4 justify-between items-start mb-4">
                                    <div className="min-w-0">
                                        {isReportableEvaluation && (
                                            <EvaluationReportsCallout
                                                evaluationId={evaluation.id}
                                                onReportsClick={() => setActiveTab('reports')}
                                            />
                                        )}
                                    </div>
                                    {runsSummary && (
                                        <div className="flex flex-col items-end gap-1">
                                            <div className="flex flex-wrap gap-4 text-sm">
                                                <div className="text-center">
                                                    <div className="font-semibold text-lg">{runsSummary.total}</div>
                                                    <div className="text-muted">Total runs</div>
                                                </div>
                                                {evaluation.output_type === 'numeric' && (
                                                    <div className="text-center">
                                                        <div className="font-semibold text-lg">
                                                            {runsSummary.scoreMean == null
                                                                ? '–'
                                                                : formatNumericEvaluationScore(runsSummary.scoreMean)}
                                                        </div>
                                                        <div className="text-muted">Mean score</div>
                                                    </div>
                                                )}
                                                {supportsRunOutcomes && (
                                                    <div className="text-center">
                                                        <div className="font-semibold text-lg text-success">
                                                            {runsSummary.successRate == null
                                                                ? '–'
                                                                : `${runsSummary.successRate}%`}
                                                        </div>
                                                        <div className="text-muted">Pass rate</div>
                                                    </div>
                                                )}
                                                {supportsRunOutcomes && originalEvaluation?.output_config.allows_na && (
                                                    <div className="text-center">
                                                        <div className="font-semibold text-lg">
                                                            {runsSummary.applicabilityRate}%
                                                        </div>
                                                        <div className="text-muted">Applicable</div>
                                                    </div>
                                                )}
                                            </div>
                                            <div className="text-muted text-xs">
                                                {runsBackfillId
                                                    ? 'From this backfill'
                                                    : runsDateRange.date_from === 'all'
                                                      ? 'Across all runs, all time'
                                                      : 'In the selected date range'}
                                            </div>
                                        </div>
                                    )}
                                </div>
                                {runsBackfillId && (
                                    <LemonBanner
                                        type="info"
                                        className="mb-4"
                                        action={{
                                            children: 'Show all runs',
                                            onClick: () =>
                                                router.actions.push(
                                                    router.values.location.pathname,
                                                    { ...router.values.searchParams, backfill_id: undefined },
                                                    router.values.hashParams
                                                ),
                                        }}
                                    >
                                        <span className="font-semibold">Showing runs from one backfill.</span>
                                        {runsBackfill && (
                                            <>
                                                {' '}
                                                It covered {pluralize(
                                                    runsBackfill.total_count,
                                                    runsBackfill.target
                                                )}{' '}
                                                between{' '}
                                                <TZLabel
                                                    time={runsBackfill.window_start}
                                                    timestampStyle="absolute"
                                                    {...RUNS_BACKFILL_TIME_FORMAT}
                                                />
                                                {' and '}
                                                <TZLabel
                                                    time={runsBackfill.window_end}
                                                    timestampStyle="absolute"
                                                    {...RUNS_BACKFILL_TIME_FORMAT}
                                                />
                                                .
                                            </>
                                        )}
                                    </LemonBanner>
                                )}
                                <EvaluationFirstResultStatus />
                                {evaluationSupportsReportHistory(originalEvaluation) && (
                                    <EvaluationLatestReport evaluationId={evaluation.id} />
                                )}
                                {!runsBackfillId && (
                                    <div className="mb-4">
                                        <EvaluationDetailResults evaluationId={evaluation.id} />
                                    </div>
                                )}
                                <EvaluationRunsTable />
                            </div>
                        ),
                    },
                    evaluationSupportsReportHistory(originalEvaluation) && {
                        key: 'reports',
                        label: 'Reports',
                        'data-attr': 'llma-evaluation-reports-tab',
                        content: (
                            <EvaluationReportsTab
                                evaluationId={evaluation.id}
                                generationDisabledReason={
                                    isReportableEvaluation ? undefined : 'Add a passing rule to generate new reports.'
                                }
                                userAccessLevel={evaluation.user_access_level ?? undefined}
                                onConfigureClick={() => setActiveTab('configuration')}
                            />
                        ),
                    },
                    {
                        key: 'backfills',
                        label: 'Backfills',
                        'data-attr': 'llma-evaluation-backfills-tab',
                        content: (
                            <EvaluationBackfillsTab
                                evaluationId={evaluation.id}
                                userAccessLevel={evaluation.user_access_level ?? undefined}
                                onConfigurationClick={() => setActiveTab('configuration')}
                            />
                        ),
                    },
                    {
                        key: 'configuration',
                        label: 'Configuration',
                        'data-attr': 'llma-evaluation-configuration-tab',
                        content: (
                            <div className="max-w-4xl mx-auto">
                                <EvaluationConfigurationForm />
                                <div className="flex justify-end mt-6">
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Evaluation}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={evaluation.user_access_level ?? undefined}
                                    >
                                        <LemonButton
                                            type="primary"
                                            onClick={handleSave}
                                            disabledReason={saveButtonDisabledReason}
                                            loading={evaluationFormSubmitting}
                                            data-attr="llma-evaluation-save-bottom"
                                        >
                                            Save changes
                                        </LemonButton>
                                    </AccessControlAction>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
            {evaluationSupportsReportHistory(originalEvaluation) && (
                <EvaluationReportDrawer
                    evaluationId={evaluation.id}
                    generateDisabledReason={
                        evaluation.user_access_level &&
                        !accessLevelSatisfied(
                            AccessControlResourceType.Evaluation,
                            toAccessControlLevel(evaluation.user_access_level),
                            AccessControlLevel.Editor
                        )
                            ? 'You need edit access to this evaluation to generate reports.'
                            : isReportableEvaluation
                              ? undefined
                              : 'Add a passing rule to generate new reports.'
                    }
                    onOpenTrace={(traceId, eventId) =>
                        router.actions.push(router.values.location.pathname, {
                            ...router.values.searchParams,
                            trace: traceId,
                            step: eventId ?? undefined,
                        })
                    }
                    onShowResults={(periodStart, periodEnd) => {
                        evaluationReportDrawerLogic({ evaluationId: evaluation.id }).actions.close()
                        setActiveTab('runs')
                        setRunsDates(periodStart, periodEnd)
                    }}
                />
            )}
            {/* Opens a report's cited trace above the report from any tab. Configuration mounts its own host for the
                preview, and two hosts on one URL would both open. */}
            {activeTab !== 'configuration' && <TraceDrawerHost listId="evaluation-runs" />}
        </div>
    )
}

export const scene: SceneExport<LLMEvaluationLogicProps> = {
    component: AIObservabilityEvaluation,
    logic: llmEvaluationLogic,
    paramsToProps: ({ params: { id }, searchParams }) => ({
        evaluationId: id && id !== 'new' ? id : 'new',
        templateKey: typeof searchParams.template === 'string' ? searchParams.template : undefined,
        evaluationType: searchParams.type === 'sentiment' ? 'sentiment' : undefined,
    }),
}
