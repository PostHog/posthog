import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useRef } from 'react'

import { IconArrowLeft, IconInfo, IconPlay, IconTrends, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { urls } from '~/scenes/urls'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { providerKeyStateIssueDescription, providerLabel } from '../settings/providerKeyStateUtils'
import { CategoricalEvaluationConfig } from './components/CategoricalEvaluationConfig'
import { EvaluationBackfillsTab } from './components/EvaluationBackfillsTab'
import { EvaluationCodeEditor } from './components/EvaluationCodeEditor'
import { EvaluationFirstResultStatus } from './components/EvaluationFirstResultStatus'
import { EvaluationLatestReport } from './components/EvaluationLatestReport'
import { EvaluationModelPicker } from './components/EvaluationModelPicker'
import { EvaluationPromptEditor } from './components/EvaluationPromptEditor'
import { EvaluationReportConfig } from './components/EvaluationReportConfig'
import { EvaluationReportsCallout } from './components/EvaluationReportsCallout'
import { EvaluationReportsTab } from './components/EvaluationReportsTab'
import { EvaluationRunsTable } from './components/EvaluationRunsTable'
import { EvaluationSettleConfig } from './components/EvaluationSettleConfig'
import { EvaluationTriggersPanel } from './components/EvaluationTriggersPanel'
import { NumericEvaluationConfig } from './components/NumericEvaluationConfig'
import {
    formatNumericEvaluationScore,
    booleanOutputConfigError,
    numericOutputConfigError,
    categoricalOutputConfigError,
} from './constants'
import { EvaluationConfigurationForm } from './create/EvaluationConfigurationForm'
import { EvaluationCreatePage } from './create/EvaluationCreatePage'
import {
    evaluationOffersSessionTarget,
    evaluationSupportsReportHistory,
    evaluationSupportsReports,
    evaluationSupportsRunOutcomes,
    evaluationTypeHasEditableCriteria,
    evaluationTypeUsesModelConfiguration,
    isBooleanEvaluationOutput,
} from './evaluationCapabilities'
import { evaluationReportLogic } from './evaluationReportLogic'
import { LLMEvaluationLogicProps, hasUnsetConditionRollout, llmEvaluationLogic } from './llmEvaluationLogic'
import { EvaluationDetailResults } from './overview/EvaluationDetailResults'
import { statusReasonLabel, statusReasonRecoveryLabel } from './statusDisplay'
import { EvaluationTarget, EvaluationType } from './types'

const RUNS_BACKFILL_TIME_FORMAT = { formatDate: 'MMM D, YYYY', formatTime: 'HH:mm' }

export function AIObservabilityEvaluation(): JSX.Element {
    const {
        evaluation,
        originalEvaluation,
        isReportableEvaluation,
        trendInsightUrl,
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
        canEnable,
        canEnableReason,
        modelSelectionRequired,
        numericBoundsRequired,
        usesDecisionModel,
    } = useValues(llmEvaluationLogic)
    const { searchParams } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const settlingStrategyEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVAL_SETTLING_STRATEGY]
    const resultsCardsEnabled = !!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_EVALUATIONS_OVERVIEW]
    const {
        setEvaluationName,
        setEvaluationDescription,
        setEvaluationEnabled,
        setAllowsNA,
        setTrueIsFailure,
        saveEvaluation,
        resetEvaluation,
        setEvaluationType,
        setOutputType,
        patchOutputConfig,
        setEvaluationTarget,
        setActiveTab,
    } = useActions(llmEvaluationLogic)
    const { push } = useActions(router)
    const triggersRef = useRef<HTMLDivElement>(null)
    const settingsUrl = combineUrl(urls.aiObservabilityEvaluations(), { ...searchParams, tab: 'settings' }).url

    useAttachedContext(
        evaluation ? [{ type: 'evaluation', key: evaluation.id || 'new', label: evaluation.name ?? undefined }] : null
    )

    if (evaluationLoading) {
        return <LemonSkeleton className="w-full h-96" />
    }

    if (!evaluation) {
        return <NotFound object="evaluation" />
    }
    if (isNewEvaluation && featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_EVALUATIONS_OVERVIEW]) {
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
    const isSessionTarget = evaluation.target === 'session'
    const offersSessionTarget = evaluationOffersSessionTarget(evaluation, settlingStrategyEnabled)
    const supportsRunOutcomes = evaluationSupportsRunOutcomes(originalEvaluation)
    const isBooleanOutput = isBooleanEvaluationOutput(evaluation.output_type)
    const hasEditableCriteria = evaluationTypeHasEditableCriteria(evaluation.evaluation_type)

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
        requestAnimationFrame(() => {
            triggersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        })
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

        const reportLogic = evaluationReportLogic({ evaluationId: isNewEvaluation ? 'new' : evaluation.id })
        if (evaluationSupportsReports(evaluation) && reportLogic.isMounted() && reportLogic.values.configError) {
            lemonToast.error(reportLogic.values.configError)
            return
        }

        saveEvaluation()
    }

    const handleCancel = (): void => {
        if (hasUnsavedChanges) {
            resetEvaluation()
        }
        push(evaluationBackTarget.path)
    }

    const hogEvaluationMethodOptions: { value: EvaluationType; label: string }[] = [
        {
            value: 'hog',
            label: 'Hog code',
        },
    ]
    const evaluationMethodOptions: { value: EvaluationType; label: string }[] = [
        {
            value: 'llm_judge',
            label: 'LLM as a judge',
        },
        ...hogEvaluationMethodOptions,
        {
            value: 'sentiment',
            label: 'Sentiment analysis',
        },
    ]

    return (
        <div className="@container/evaluation min-w-0 space-y-6">
            <SceneBreadcrumbBackButton />
            {/* Header */}
            <SceneStickyBar
                hasSceneTitleSection={false}
                className="flex flex-col justify-between items-start gap-4 space-y-0 @min-[64rem]/evaluation:flex-row"
            >
                <div className="space-y-2 min-w-0">
                    <h1 className="text-2xl font-semibold break-words">
                        {isNewEvaluation ? 'New evaluation' : evaluation.name}
                    </h1>
                    <div className="flex flex-wrap items-center gap-2">
                        {isNewEvaluation ? (
                            <LemonTag type="primary">New</LemonTag>
                        ) : (
                            <>
                                {evaluation.status === 'error' ? (
                                    <LemonTag type="danger" icon={<IconWarning />}>
                                        Error
                                    </LemonTag>
                                ) : (
                                    <LemonTag type={evaluation.enabled ? 'success' : 'default'}>
                                        {evaluation.enabled ? 'Enabled' : 'Disabled'}
                                    </LemonTag>
                                )}
                                {hasUnsavedChanges && <LemonTag type="warning">Unsaved changes</LemonTag>}
                            </>
                        )}
                    </div>
                </div>
                <div className="flex flex-wrap gap-2 max-w-full">
                    {trendInsightUrl ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconTrends />}
                            to={trendInsightUrl}
                            targetBlank
                            data-attr="llma-evaluation-trend-insight"
                        >
                            Trend insight
                        </LemonButton>
                    ) : null}
                    {openInPlaygroundUrl ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconPlay />}
                            to={openInPlaygroundUrl}
                            data-attr="llma-playground-open-from-evaluation"
                        >
                            Open in Playground
                        </LemonButton>
                    ) : null}
                    <LemonButton type="secondary" icon={<IconArrowLeft />} onClick={handleCancel}>
                        {hasUnsavedChanges ? 'Cancel' : 'Back'}
                    </LemonButton>
                    {showSaveAction && (
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
                            >
                                {isNewEvaluation ? 'Create evaluation' : 'Save changes'}
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </div>
            </SceneStickyBar>

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
                    !isNewEvaluation && {
                        key: 'runs',
                        label: 'Runs',
                        'data-attr': 'llma-evaluation-runs-tab',
                        content: (
                            <div className="max-w-6xl">
                                <div className="flex flex-wrap gap-4 justify-between items-center mb-4">
                                    <div className="min-w-0">
                                        <p className="text-muted text-sm m-0">
                                            History of when this evaluation has been executed.
                                        </p>

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
                                {resultsCardsEnabled && (
                                    <>
                                        <EvaluationFirstResultStatus />
                                        {evaluationSupportsReportHistory(originalEvaluation) && (
                                            <EvaluationLatestReport
                                                evaluationId={evaluation.id}
                                                onOpenReports={() => setActiveTab('reports')}
                                            />
                                        )}
                                    </>
                                )}
                                {resultsCardsEnabled && !runsBackfillId && (
                                    <div className="mb-4">
                                        <EvaluationDetailResults evaluationId={evaluation.id} />
                                    </div>
                                )}
                                <EvaluationRunsTable />
                            </div>
                        ),
                    },
                    !isNewEvaluation &&
                        evaluationSupportsReportHistory(originalEvaluation) && {
                            key: 'reports',
                            label: 'Reports',
                            'data-attr': 'llma-evaluation-reports-tab',
                            content: (
                                <EvaluationReportsTab
                                    evaluationId={evaluation.id}
                                    generationDisabledReason={
                                        isReportableEvaluation
                                            ? undefined
                                            : 'Add a passing rule to generate new reports.'
                                    }
                                    userAccessLevel={evaluation.user_access_level ?? undefined}
                                    onConfigureClick={() => setActiveTab('configuration')}
                                />
                            ),
                        },
                    !isNewEvaluation && {
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
                            // The step layout is centered, like the new evaluation page. The old form stays on the left.
                            <div
                                className={resultsCardsEnabled && !isNewEvaluation ? 'max-w-4xl mx-auto' : 'max-w-4xl'}
                            >
                                {resultsCardsEnabled && !isNewEvaluation ? (
                                    <EvaluationConfigurationForm />
                                ) : (
                                    <div className="space-y-6">
                                        {/* Basic Information */}
                                        <div className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6">
                                            <h3 className="text-lg font-semibold mb-4">Basic information</h3>

                                            <div className="space-y-4">
                                                <LemonField.Pure label="Name">
                                                    <LemonInput
                                                        value={evaluation.name}
                                                        onChange={setEvaluationName}
                                                        placeholder="e.g., Helpfulness Check"
                                                        maxLength={100}
                                                    />
                                                </LemonField.Pure>

                                                {evaluationMethodOptions.length > 1 && (
                                                    <LemonField.Pure label="Method">
                                                        <LemonSelect
                                                            value={evaluation.evaluation_type}
                                                            onChange={(value) =>
                                                                setEvaluationType(value as EvaluationType)
                                                            }
                                                            options={evaluationMethodOptions.map((option) => ({
                                                                ...option,
                                                                disabledReason:
                                                                    !isNewEvaluation &&
                                                                    ['numeric', 'categorical'].includes(
                                                                        evaluation.output_type
                                                                    ) &&
                                                                    option.value === 'sentiment'
                                                                        ? 'Create a new evaluation to change its output type.'
                                                                        : undefined,
                                                            }))}
                                                            fullWidth
                                                        />
                                                    </LemonField.Pure>
                                                )}
                                                <p className="text-muted text-sm -mt-2">
                                                    {isSentiment ? (
                                                        'Classify the sentiment of only the last user message on each matching generation event with a sentiment classifier, not LLM calls. The classifier is trained on English, so labels are unreliable for other languages. For a multilingual agent, use an LLM judge instead.'
                                                    ) : isHog ? (
                                                        <>
                                                            Run deterministic{' '}
                                                            <Link to="https://posthog.com/docs/hog" target="_blank">
                                                                Hog code
                                                            </Link>{' '}
                                                            against{' '}
                                                            {isSessionTarget
                                                                ? 'the whole session'
                                                                : evaluation.target === 'trace'
                                                                  ? 'the whole trace'
                                                                  : 'each generation'}
                                                            . No LLM cost.
                                                        </>
                                                    ) : (
                                                        `Use an LLM to evaluate ${
                                                            isSessionTarget
                                                                ? 'the whole session'
                                                                : evaluation.target === 'trace'
                                                                  ? 'the whole trace'
                                                                  : 'each generation'
                                                        } against a natural-language prompt.`
                                                    )}
                                                </p>

                                                {!isSentiment && (
                                                    <>
                                                        <LemonField.Pure label="Evaluate">
                                                            <LemonSelect<EvaluationTarget>
                                                                value={evaluation.target ?? 'generation'}
                                                                onChange={setEvaluationTarget}
                                                                options={[
                                                                    {
                                                                        value: 'generation',
                                                                        label: 'Each generation',
                                                                    },
                                                                    {
                                                                        value: 'trace',
                                                                        label: 'Whole trace',
                                                                    },
                                                                    ...(offersSessionTarget
                                                                        ? [
                                                                              {
                                                                                  value: 'session' as const,
                                                                                  label: 'Whole session',
                                                                              },
                                                                          ]
                                                                        : []),
                                                                ]}
                                                                fullWidth
                                                            />
                                                        </LemonField.Pure>
                                                        <p className="text-muted text-sm -mt-2">
                                                            {isSessionTarget
                                                                ? 'Runs once per session on every trace it contains, after the session settles. Only fires for generations that have an $ai_session_id property.'
                                                                : evaluation.target === 'trace'
                                                                  ? 'Runs once per trace on all of its events together, after it settles. Only fires for generations that have an $ai_trace_id property.'
                                                                  : 'Runs on each matching generation event individually, right after it is ingested.'}
                                                        </p>
                                                        <EvaluationSettleConfig />
                                                    </>
                                                )}

                                                {!isSentiment && (
                                                    <LemonField.Pure label="Output type">
                                                        <LemonSelect
                                                            value={evaluation.output_type}
                                                            options={[
                                                                { value: 'boolean', label: 'Boolean' },
                                                                { value: 'categorical', label: 'Categorical' },
                                                                { value: 'numeric', label: 'Numeric score' },
                                                            ]}
                                                            onChange={(value) =>
                                                                setOutputType(
                                                                    value as 'boolean' | 'numeric' | 'categorical'
                                                                )
                                                            }
                                                            disabledReason={
                                                                !isNewEvaluation
                                                                    ? 'Create a new evaluation to change its output type.'
                                                                    : undefined
                                                            }
                                                            data-attr="llma-evaluation-output-type"
                                                        />
                                                    </LemonField.Pure>
                                                )}
                                                {evaluation.output_type === 'categorical' && (
                                                    <CategoricalEvaluationConfig
                                                        config={evaluation.output_config}
                                                        onChange={patchOutputConfig}
                                                    />
                                                )}
                                                {evaluation.output_type === 'numeric' && (
                                                    <NumericEvaluationConfig
                                                        config={evaluation.output_config}
                                                        onChange={patchOutputConfig}
                                                        requiresBounds={numericBoundsRequired}
                                                    />
                                                )}
                                                <LemonField.Pure label="Description (optional)">
                                                    <LemonTextArea
                                                        value={evaluation.description || ''}
                                                        onChange={setEvaluationDescription}
                                                        placeholder="Describe what this evaluation checks for..."
                                                        rows={2}
                                                        maxLength={500}
                                                    />
                                                </LemonField.Pure>

                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Tooltip
                                                        title={canEnableReason}
                                                        visible={canEnableReason ? undefined : false}
                                                    >
                                                        <span>
                                                            <LemonSwitch
                                                                checked={evaluation.enabled}
                                                                onChange={setEvaluationEnabled}
                                                                label="Enable evaluation"
                                                                disabled={!canEnable && !evaluation.enabled}
                                                            />
                                                        </span>
                                                    </Tooltip>
                                                    <span className="text-muted text-sm">
                                                        {!canEnable && !evaluation.enabled
                                                            ? canEnableReason
                                                            : evaluation.enabled
                                                              ? 'This evaluation will run automatically based on triggers'
                                                              : 'This evaluation is paused and will not run'}
                                                    </span>
                                                </div>

                                                {isBooleanOutput && (
                                                    <LemonField.Pure
                                                        label={
                                                            <div className="flex items-center gap-1">
                                                                <span>Allow N/A responses</span>
                                                                <Tooltip
                                                                    title={
                                                                        isHog
                                                                            ? 'When enabled, returning null from your Hog code means "not applicable" instead of being treated as an error.'
                                                                            : 'Sometimes forcing a True or False is not enough and you want the LLM to decide if the evaluation is applicable or not. Enable this when the evaluation criteria may not apply to all generations.'
                                                                    }
                                                                >
                                                                    <IconInfo className="text-muted text-base" />
                                                                </Tooltip>
                                                            </div>
                                                        }
                                                    >
                                                        <div className="flex flex-wrap items-center gap-2">
                                                            <LemonSwitch
                                                                checked={evaluation.output_config.allows_na ?? false}
                                                                onChange={setAllowsNA}
                                                            />
                                                            <span className="text-muted text-sm">
                                                                {evaluation.output_config.allows_na
                                                                    ? isHog
                                                                        ? 'Returning null means "Not Applicable"'
                                                                        : 'Evaluation can return "Not Applicable" when criteria doesn\'t apply'
                                                                    : isHog
                                                                      ? 'Evaluation must return true or false'
                                                                      : 'Evaluation returns true or false'}
                                                            </span>
                                                        </div>
                                                    </LemonField.Pure>
                                                )}

                                                {isBooleanOutput && (
                                                    <LemonField.Pure
                                                        label={
                                                            <div className="flex items-center gap-1">
                                                                <span>A true result flags a problem</span>
                                                                <Tooltip title="Turn this on when the evaluation looks for something you don't want, like a struggling user or a hallucination. A true result then counts as a fail in reports and pass rates. The evaluation results themselves don't change.">
                                                                    <IconInfo className="text-muted text-base" />
                                                                </Tooltip>
                                                            </div>
                                                        }
                                                    >
                                                        <div className="flex flex-wrap items-center gap-2">
                                                            <LemonSwitch
                                                                checked={
                                                                    evaluation.output_config.true_is_failure ?? false
                                                                }
                                                                onChange={setTrueIsFailure}
                                                                data-attr="llma-evaluation-true-is-failure-switch"
                                                            />
                                                            <span className="text-muted text-sm">
                                                                {evaluation.output_config.true_is_failure
                                                                    ? 'A true result counts as a fail'
                                                                    : 'A true result counts as a pass'}
                                                            </span>
                                                        </div>
                                                    </LemonField.Pure>
                                                )}
                                            </div>
                                        </div>

                                        {/* Prompt / Code Configuration */}
                                        {hasEditableCriteria && (
                                            <div className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6">
                                                <h3 className="text-lg font-semibold mb-4">
                                                    {isHog ? 'Evaluation code' : 'Evaluation prompt'}
                                                </h3>
                                                {isHog ? <EvaluationCodeEditor /> : <EvaluationPromptEditor />}
                                            </div>
                                        )}

                                        {/* Judge Model Configuration (LLM judge only) */}
                                        {evaluationTypeUsesModelConfiguration(evaluation.evaluation_type) && (
                                            <EvaluationModelPicker />
                                        )}

                                        {/* Trigger Configuration */}
                                        <div
                                            ref={triggersRef}
                                            className="bg-bg-light border rounded p-4 @min-[40rem]/evaluation:p-6"
                                        >
                                            <h3 className="text-lg font-semibold mb-4">Triggers</h3>
                                            <EvaluationTriggersPanel />
                                        </div>

                                        {/* Scheduled Reports (inline config for new evaluations) */}
                                        {isNewEvaluation && isReportableEvaluation && (
                                            <EvaluationReportConfig evaluationId="new" />
                                        )}
                                    </div>
                                )}

                                {/* Scheduled Reports (for existing evaluations, outside the form). The new form sets them in its sentence. */}
                                {!resultsCardsEnabled && !isNewEvaluation && isReportableEvaluation && (
                                    <div className="mt-6">
                                        <EvaluationReportConfig evaluationId={evaluation.id} />
                                    </div>
                                )}
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
                                            {isNewEvaluation ? 'Create evaluation' : 'Save changes'}
                                        </LemonButton>
                                    </AccessControlAction>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
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
