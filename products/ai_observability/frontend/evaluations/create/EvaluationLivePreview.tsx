import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { TraceDrawerRowsSync, useTraceDrawerRows } from '../../redesign/trace/TraceDrawerRowsHost'
import { JUDGE_TEST_LIMIT, evaluationPreviewLogic, outputConfigError, testableKind } from '../evaluationPreviewLogic'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { ChecklistItem, ChecklistKey, PreviewStep } from './creationChecklist'
import { EvaluationCreateButton } from './EvaluationCreateButton'
import { EvaluationCreateChecklist } from './EvaluationCreateChecklist'
import { EvaluationPastTrafficOption } from './EvaluationPastTrafficOption'
import { EvaluationPreviewRuns } from './EvaluationPreviewRuns'
import { EvaluationPreviewTestButton } from './EvaluationPreviewTestButton'
import { EvaluationSentence } from './EvaluationSentence'
import { reportText } from './evaluationSummary'
import { PREVIEW_DRAWER_LIST_ID, PREVIEW_TRACE_LINK_CLASS, previewRuns } from './previewRuns'

/** "a daily report", "a report every 100 results", or "no reports". */
function reportPhrase(cadence: string): string {
    if (cadence === 'never') {
        return 'no reports'
    }
    return cadence.startsWith('every') ? `a report ${cadence}` : `a ${cadence} report`
}

/**
 * A live preview of the evaluation being set up: one sentence that says what it does, and the real traffic it
 * would run on with each run's result. Every part of the sentence opens the step that sets it.
 */
export function EvaluationLivePreview({
    steps,
    currentIndex,
    checklist,
    onGo,
    onCreate,
}: {
    steps: PreviewStep[]
    currentIndex: number
    checklist: ChecklistItem[]
    onGo: (index: number) => void
    onCreate?: () => void
}): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const {
        evaluation,
        usesDecisionModel,
        selectedModelName,
        selectedModel,
        isReportableEvaluation,
        isNewEvaluation,
        checkPastTraffic,
    } = useValues(llmEvaluationLogic)
    const { setCheckPastTraffic } = useActions(llmEvaluationLogic)
    const { configDraft } = useValues(evaluationReportLogic({ evaluationId: props.evaluationId }))
    const previewLogic = evaluationPreviewLogic(props)
    const { rows, samplesLoading, samplesError, testResults, testResultsLoading, testError, testDiscarded } =
        useValues(previewLogic)
    const { testRows } = useActions(previewLogic)
    const { volume } = useValues(evaluationVolumeLogic)
    const { rowProps } = useTraceDrawerRows(PREVIEW_DRAWER_LIST_ID, `.${PREVIEW_TRACE_LINK_CLASS}`)
    // A failed run, such as code that no longer compiles, leaves the last results behind, so they stop showing.
    const runs = useMemo(
        () => (evaluation ? previewRuns(rows, testError ? null : testResults, evaluation) : []),
        [rows, testResults, testError, evaluation]
    )
    const drawerRows = useMemo(() => runs.flatMap((run) => run.drawerRow ?? []), [runs])

    if (!evaluation) {
        return null
    }
    const kind = testableKind(evaluation)
    const unit = evaluation.target
    const cadence = reportText({ ...configDraft, enabled: configDraft.enabled && isReportableEvaluation })
    const missing: Partial<Record<ChecklistKey, string>> = Object.fromEntries(
        checklist.filter((item) => !item.done).map((item) => [item.key, item.todo])
    )
    // Only a judge shows the test button, so it counts the runs a judge test covers.
    const testCount = Math.min(rows.length, JUDGE_TEST_LIMIT)
    const sampledBelowAll = evaluation.conditions.some((condition) => (condition.rollout_percentage ?? 100) < 100)

    return (
        <aside
            className="flex flex-col gap-4 rounded border bg-bg-light p-4 @min-[44rem]/evaluation:sticky @min-[44rem]/evaluation:top-4"
            aria-label="Preview"
            data-attr="llma-evaluation-create-live-preview"
        >
            <div className="flex flex-col gap-1.5">
                <h3 className="mb-0 truncate text-base font-semibold">
                    {evaluation.name.trim() || 'Untitled evaluation'}
                </h3>
                <EvaluationSentence
                    evaluation={evaluation}
                    usesDecisionModel={usesDecisionModel}
                    // An unpicked model comes back as an empty string, not null, so `||` falls through to the placeholder.
                    model={selectedModelName || selectedModel || 'a model'}
                    reports={reportPhrase(cadence)}
                    steps={steps}
                    currentIndex={currentIndex}
                    missing={missing}
                    onOpen={(index, part) => {
                        if (index === currentIndex) {
                            return
                        }
                        // pinned: analytics event name and properties, because the creation funnel reads them
                        posthog.capture('llma evaluation create part opened', { part, is_new: isNewEvaluation })
                        onGo(index)
                    }}
                />
            </div>
            {/* Rows hold customer prompts, so autocapture and session replay must not record them. */}
            <div className="ph-no-capture flex flex-col gap-2" data-attr="llma-evaluation-create-preview">
                <EvaluationPreviewRuns
                    unit={unit}
                    runs={runs}
                    loading={samplesLoading && rows.length === 0}
                    loadFailed={samplesError}
                    // The count comes from all matching traffic, the rows only from the sampled part of it.
                    noneInSample={sampledBelowAll && (volume?.matchingUnits ?? 0) > 0}
                    live={kind === 'hog'}
                    testing={testResultsLoading}
                    rowProps={(run) => rowProps(run.drawerRow)}
                />
                {steps[currentIndex]?.key === 'check' && evaluation.evaluation_type === 'llm_judge' && (
                    <EvaluationPreviewTestButton
                        count={testCount}
                        unit={unit}
                        loading={testResultsLoading}
                        userAccessLevel={evaluation.user_access_level ?? undefined}
                        onTest={() => testRows({ auto: false })}
                        disabledReason={
                            !kind
                                ? 'Write a prompt and pick a model first'
                                : (outputConfigError(evaluation) ??
                                  // Rows from the previous filters would skip the new ones, so wait for the current sample.
                                  (samplesError
                                      ? `Couldn't load the matching ${unit}s`
                                      : samplesLoading
                                        ? `Loading the matching ${unit}s`
                                        : testCount === 0
                                          ? `No ${unit}s to test`
                                          : undefined))
                        }
                    />
                )}
                {testError && (
                    <p className="mb-0 break-words text-xs text-danger" data-attr="llma-evaluation-create-test-error">
                        {testError}
                    </p>
                )}
                {testDiscarded && (
                    <p className="mb-0 text-xs text-secondary" data-attr="llma-evaluation-create-test-discarded">
                        The evaluation changed while the test ran, so its results don't apply. Test again.
                    </p>
                )}
            </div>
            {isNewEvaluation && (
                <EvaluationCreateChecklist
                    checklist={checklist}
                    startsPaused={!evaluation.enabled}
                    onOpen={(item) => {
                        const index = steps.findIndex((step) => step.checks.includes(item.key))
                        if (index >= 0) {
                            onGo(index)
                        }
                    }}
                >
                    {/* Here and not on the "Runs on" step, because picking a model on a later step decides
                        whether the evaluation starts running. */}
                    {evaluation.enabled && (
                        <EvaluationPastTrafficOption
                            checked={checkPastTraffic}
                            onChange={setCheckPastTraffic}
                            volume={volume}
                            callsJudge={evaluation.evaluation_type === 'llm_judge'}
                        />
                    )}
                    {onCreate && currentIndex < steps.length - 1 && (
                        <EvaluationCreateButton
                            onCreate={onCreate}
                            fullWidth
                            data-attr="llma-evaluation-create-submit-preview"
                        />
                    )}
                </EvaluationCreateChecklist>
            )}
            <TraceDrawerRowsSync listId={PREVIEW_DRAWER_LIST_ID} rows={drawerRows} />
        </aside>
    )
}
