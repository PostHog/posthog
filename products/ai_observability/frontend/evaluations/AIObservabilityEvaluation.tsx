import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
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
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { NotFound } from 'lib/components/NotFound'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { urls } from '~/scenes/urls'
import { AccessControlLevel, AccessControlResourceType, ChartDisplayType, HogQLMathType } from '~/types'

import { getModelPickerFooterLink, ModelPicker } from '../ModelPicker'
import { modelPickerLogic } from '../modelPickerLogic'
import { providerKeyStateIssueDescription, providerLabel } from '../settings/providerKeyStateUtils'
import { EvaluationCodeEditor } from './components/EvaluationCodeEditor'
import { EvaluationPromptEditor } from './components/EvaluationPromptEditor'
import { EvaluationReportConfig } from './components/EvaluationReportConfig'
import { EvaluationReportsTab } from './components/EvaluationReportsTab'
import { EvaluationRunsTable } from './components/EvaluationRunsTable'
import { EvaluationTriggers } from './components/EvaluationTriggers'
import {
    evaluationSupportsReports,
    evaluationTypeHasEditableCriteria,
    evaluationTypeSupportsSignalEmission,
    evaluationTypeUsesModelConfiguration,
} from './evaluationCapabilities'
import { DEFAULT_TRACE_WINDOW_SECONDS, LLMEvaluationLogicProps, llmEvaluationLogic } from './llmEvaluationLogic'
import { statusReasonLabel, statusReasonRecoveryLabel } from './statusDisplay'
import { EvaluationTarget, EvaluationType } from './types'

export function AIObservabilityEvaluation(): JSX.Element {
    const {
        evaluation,
        evaluationLoading,
        evaluationFormSubmitting,
        hasUnsavedChanges,
        formValid,
        isNewEvaluation,
        runsSummary,
        evaluationProviderKeyIssue,
        signalEmissionEnabled,
        activeTab,
        canEnable,
        canEnableReason,
    } = useValues(llmEvaluationLogic)
    const { user } = useValues(userLogic)
    const { searchParams } = useValues(router)
    const {
        setEvaluationName,
        setEvaluationDescription,
        setEvaluationEnabled,
        setAllowsNA,
        saveEvaluation,
        resetEvaluation,
        setEvaluationType,
        setEvaluationTarget,
        setTraceWindowSeconds,
        setSignalEmission,
        setActiveTab,
    } = useActions(llmEvaluationLogic)
    const { push } = useActions(router)
    const triggersRef = useRef<HTMLDivElement>(null)
    const settingsUrl = combineUrl(urls.aiObservabilityEvaluations(), { ...searchParams, tab: 'settings' }).url

    if (evaluationLoading) {
        return <LemonSkeleton className="w-full h-96" />
    }

    if (!evaluation) {
        return <NotFound object="evaluation" />
    }
    const openInPlaygroundUrl =
        evaluationTypeUsesModelConfiguration(evaluation.evaluation_type) && evaluation.id
            ? combineUrl(urls.aiObservabilityPlayground(), { source_evaluation_id: evaluation.id }).url
            : null

    const isHog = evaluation.evaluation_type === 'hog'
    const isSentiment = evaluation.evaluation_type === 'sentiment'
    const isReportableEvaluation = evaluationSupportsReports(evaluation)
    const hasEditableCriteria = evaluationTypeHasEditableCriteria(evaluation.evaluation_type)

    const trendInsightUrl =
        isReportableEvaluation && !isNewEvaluation && evaluation.id
            ? urls.insightNew({
                  query: {
                      kind: NodeKind.InsightVizNode,
                      source: {
                          kind: NodeKind.TrendsQuery,
                          series: [
                              {
                                  kind: NodeKind.EventsNode,
                                  event: '$ai_evaluation',
                                  custom_name: `${evaluation.name} — Pass rate`,
                                  math: HogQLMathType.HogQL,
                                  math_hogql: `if(countIf(properties.$ai_evaluation_result IS NOT NULL) > 0, countIf(properties.$ai_evaluation_result = 1) / countIf(properties.$ai_evaluation_result IS NOT NULL) * 100, 0)`,
                                  properties: [
                                      {
                                          key: '$ai_evaluation_id',
                                          value: evaluation.id,
                                          operator: 'exact',
                                          type: 'event',
                                      },
                                  ],
                              },
                              ...(evaluation.output_config.allows_na
                                  ? [
                                        {
                                            kind: NodeKind.EventsNode as const,
                                            event: '$ai_evaluation',
                                            custom_name: `${evaluation.name} — N/A rate`,
                                            math: HogQLMathType.HogQL as const,
                                            math_hogql: `if(count() > 0, countIf(properties.$ai_evaluation_result IS NULL) / count() * 100, 0)`,
                                            properties: [
                                                {
                                                    key: '$ai_evaluation_id',
                                                    value: evaluation.id,
                                                    operator: 'exact' as const,
                                                    type: 'event' as const,
                                                },
                                            ],
                                        },
                                    ]
                                  : []),
                          ],
                          trendsFilter: {
                              display: ChartDisplayType.ActionsLineGraph,
                          },
                          dateRange: {
                              date_from: '-7d',
                          },
                          interval: 'day',
                      },
                  } as InsightVizNode,
              })
            : null

    const configValid = isHog
        ? evaluation.evaluation_config.source.trim().length > 0
        : isSentiment
          ? true
          : evaluation.evaluation_config.prompt.trim().length > 0
    const hasName = evaluation.name.length > 0
    const basicFieldsValid = hasName && configValid
    const percentageUnset = evaluation.conditions.some((c) => (c.rollout_percentage ?? 0) === 0)
    const percentageOutOfRange = evaluation.conditions.some(
        (c) => (c.rollout_percentage ?? 0) > 100 || (c.rollout_percentage ?? 0) < 0
    )
    const hasConditions = evaluation.conditions.length > 0
    const saveButtonDisabledReason = !hasName
        ? 'Add a name for this evaluation'
        : !configValid
          ? isHog
              ? 'Add evaluation code before saving'
              : 'Add an evaluation prompt before saving'
          : undefined

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

        saveEvaluation()
    }

    const handleCancel = (): void => {
        if (hasUnsavedChanges) {
            resetEvaluation()
        }
        push(combineUrl(urls.aiObservabilityEvaluations(), searchParams).url)
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
        <div className="space-y-6">
            <SceneBreadcrumbBackButton />
            {/* Header */}
            <div className="flex justify-between items-start pb-4 border-b">
                <div className="space-y-2">
                    <h1 className="text-2xl font-semibold">{isNewEvaluation ? 'New evaluation' : evaluation.name}</h1>
                    <div className="flex items-center gap-2">
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
                <div className="flex gap-2">
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
                    {activeTab !== 'runs' && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
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
            </div>

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
                                <div className="flex justify-between items-center mb-4">
                                    <p className="text-muted text-sm m-0">
                                        History of when this evaluation has been executed.
                                    </p>
                                    {runsSummary && (
                                        <div className="flex gap-4 text-sm">
                                            <div className="text-center">
                                                <div className="font-semibold text-lg">{runsSummary.total}</div>
                                                <div className="text-muted">Total runs</div>
                                            </div>
                                            {isReportableEvaluation && (
                                                <div className="text-center">
                                                    <div className="font-semibold text-lg text-success">
                                                        {runsSummary.successRate}%
                                                    </div>
                                                    <div className="text-muted">Success rate</div>
                                                </div>
                                            )}
                                            {isReportableEvaluation && evaluation.output_config.allows_na && (
                                                <div className="text-center">
                                                    <div className="font-semibold text-lg">
                                                        {runsSummary.applicabilityRate}%
                                                    </div>
                                                    <div className="text-muted">Applicable</div>
                                                </div>
                                            )}
                                            <div className="text-center">
                                                <div className="font-semibold text-lg text-danger">
                                                    {runsSummary.errors}
                                                </div>
                                                <div className="text-muted">Errors</div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                                <EvaluationRunsTable />
                            </div>
                        ),
                    },
                    !isNewEvaluation &&
                        isReportableEvaluation && {
                            key: 'reports',
                            label: 'Reports',
                            'data-attr': 'llma-evaluation-reports-tab',
                            content: (
                                <EvaluationReportsTab
                                    evaluationId={evaluation.id}
                                    onConfigureClick={() => setActiveTab('configuration')}
                                />
                            ),
                        },
                    {
                        key: 'configuration',
                        label: 'Configuration',
                        'data-attr': 'llma-evaluation-configuration-tab',
                        content: (
                            <div className="max-w-4xl">
                                <Form logic={llmEvaluationLogic} formKey="evaluation" className="space-y-6">
                                    {/* Basic Information */}
                                    <div className="bg-bg-light border rounded p-6">
                                        <h3 className="text-lg font-semibold mb-4">Basic information</h3>

                                        <div className="space-y-4">
                                            <Field name="name" label="Name">
                                                <LemonInput
                                                    value={evaluation.name}
                                                    onChange={setEvaluationName}
                                                    placeholder="e.g., Helpfulness Check"
                                                    maxLength={100}
                                                />
                                            </Field>

                                            {evaluationMethodOptions.length > 1 && (
                                                <Field name="evaluation_type" label="Method">
                                                    <LemonSelect
                                                        value={evaluation.evaluation_type}
                                                        onChange={(value) => setEvaluationType(value as EvaluationType)}
                                                        options={evaluationMethodOptions}
                                                        fullWidth
                                                    />
                                                </Field>
                                            )}
                                            <p className="text-muted text-sm -mt-2">
                                                {isSentiment ? (
                                                    'Classify the sentiment of only the last user message on each matching generation event with a sentiment classifier, not LLM calls.'
                                                ) : isHog ? (
                                                    <>
                                                        Run deterministic{' '}
                                                        <Link to="https://posthog.com/docs/hog" target="_blank">
                                                            Hog code
                                                        </Link>{' '}
                                                        against each generation. No LLM cost, instant results.
                                                    </>
                                                ) : (
                                                    'Use an LLM to evaluate each generation against a natural-language prompt.'
                                                )}
                                            </p>

                                            {!isSentiment && (
                                                <>
                                                    <Field name="target" label="Evaluate">
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
                                                            ]}
                                                            fullWidth
                                                        />
                                                    </Field>
                                                    <p className="text-muted text-sm -mt-2">
                                                        {evaluation.target === 'trace'
                                                            ? 'Runs once per trace on all of its events together, after a delay that lets the trace complete.'
                                                            : 'Runs on each matching generation event individually, right after it is ingested.'}
                                                    </p>
                                                    {evaluation.target === 'trace' && (
                                                        <Field name="trace_window" label="Wait before evaluating">
                                                            <div className="space-y-1">
                                                                <DurationPicker
                                                                    value={
                                                                        evaluation.target_config.window_seconds ??
                                                                        DEFAULT_TRACE_WINDOW_SECONDS
                                                                    }
                                                                    onChange={setTraceWindowSeconds}
                                                                />
                                                                <p className="text-muted text-xs">
                                                                    How long to wait after the first matching generation
                                                                    before pulling the whole trace (10s–2h). Captured
                                                                    when the run is scheduled — changing it won't affect
                                                                    trace runs already in flight.
                                                                </p>
                                                            </div>
                                                        </Field>
                                                    )}
                                                </>
                                            )}

                                            <Field name="description" label="Description (optional)">
                                                <LemonTextArea
                                                    value={evaluation.description || ''}
                                                    onChange={setEvaluationDescription}
                                                    placeholder="Describe what this evaluation checks for..."
                                                    rows={2}
                                                    maxLength={500}
                                                />
                                            </Field>

                                            <div className="flex items-center gap-2">
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

                                            {isReportableEvaluation && (
                                                <Field
                                                    name="allows_na"
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
                                                    <div className="flex items-center gap-2">
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
                                                </Field>
                                            )}
                                            {!isNewEvaluation &&
                                                user?.is_staff &&
                                                evaluationTypeSupportsSignalEmission(evaluation.evaluation_type) && (
                                                    <div className="flex items-center gap-2">
                                                        <LemonSwitch
                                                            checked={signalEmissionEnabled}
                                                            onChange={setSignalEmission}
                                                        />
                                                        <span>Emit signals</span>
                                                        <Tooltip title="When enabled, true verdicts from this evaluation will be emitted as signals for clustering and investigation.">
                                                            <IconInfo className="text-muted text-base" />
                                                        </Tooltip>
                                                    </div>
                                                )}
                                        </div>
                                    </div>

                                    {/* Prompt / Code Configuration */}
                                    {hasEditableCriteria && (
                                        <div className="bg-bg-light border rounded p-6">
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
                                    <div ref={triggersRef} className="bg-bg-light border rounded p-6">
                                        <h3 className="text-lg font-semibold mb-4">Triggers</h3>
                                        <p className="text-muted text-sm mb-4">
                                            Configure when this evaluation should run on your LLM generations.
                                        </p>
                                        <EvaluationTriggers />
                                    </div>

                                    {/* Scheduled Reports (inline config for new evaluations) */}
                                    {isNewEvaluation && isReportableEvaluation && (
                                        <EvaluationReportConfig evaluationId="new" />
                                    )}
                                </Form>

                                {/* Scheduled Reports (for existing evaluations, outside the form) */}
                                {!isNewEvaluation && isReportableEvaluation && (
                                    <div className="mt-6">
                                        <EvaluationReportConfig evaluationId={evaluation.id} />
                                    </div>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function EvaluationModelPicker(): JSX.Element {
    const {
        hasByokKeys,
        byokModels,
        trialModels,
        providerModelGroups,
        trialProviderModelGroups,
        byokModelsLoading,
        trialModelsLoading,
        providerKeysLoading,
    } = useValues(modelPickerLogic)
    const { selectedModel, selectedPickerProviderKeyId, requiresProviderKey } = useValues(llmEvaluationLogic)
    const { selectModelFromPicker } = useActions(llmEvaluationLogic)

    const showTrialModels = !hasByokKeys && !requiresProviderKey
    const allModels = showTrialModels ? trialModels : byokModels
    const selectedModelName = allModels.find((m) => m.id === selectedModel)?.name
    const groups = showTrialModels ? trialProviderModelGroups : providerModelGroups
    const loading = showTrialModels ? trialModelsLoading : byokModelsLoading || providerKeysLoading

    const footerLink = getModelPickerFooterLink(hasByokKeys)

    return (
        <div className="bg-bg-light border rounded p-6">
            <h3 className="text-lg font-semibold mb-2">Judge model</h3>
            <p className="text-muted text-sm mb-4">
                Select which LLM provider and model to use for running this evaluation.
            </p>

            <div className="space-y-4">
                <Field name="model" label="Model">
                    <ModelPicker
                        model={selectedModel}
                        selectedProviderKeyId={selectedPickerProviderKeyId}
                        onSelect={selectModelFromPicker}
                        groups={groups}
                        loading={loading}
                        footerLink={footerLink}
                        selectedModelName={selectedModelName}
                        data-attr="evaluation-model-selector"
                    />
                </Field>
            </div>
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
