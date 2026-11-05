import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { urls } from '~/scenes/urls'

import type { EvaluationSampleTrafficItemApi, TestHogResultItemApi } from '../../generated/api.schemas'
import { TraceDrawerRowsSync, useTraceDrawerRows } from '../../redesign/trace/TraceDrawerRowsHost'
import type { TraceListRow } from '../../redesign/trace/traceListRows'
import {
    JUDGE_TEST_LIMIT,
    evaluationPreviewLogic,
    outputConfigError,
    resultPasses,
    testableKind,
} from '../evaluationPreviewLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationConfig } from '../types'

/** The drawer host renders outside the sticky preview panel, whose stacking context would trap it under the page. */
export const PREVIEW_DRAWER_LIST_ID = 'evaluation-preview'
const TRACE_LINK = '.llma-evaluation-preview-trace-link'
// Rows arrive one after another, so a new filter reads as the traffic changing. Tailwind needs literal classes.
const ROW_STAGGER = [
    '',
    '[animation-delay:60ms]',
    '[animation-delay:120ms]',
    '[animation-delay:180ms]',
    '[animation-delay:240ms]',
    '[animation-delay:300ms]',
]

function ResultTag({
    result,
    evaluation,
}: {
    result: TestHogResultItemApi
    evaluation: EvaluationConfig
}): JSX.Element {
    const passes = resultPasses(result, evaluation)
    // An empty list is a real answer from a multiple-choice evaluation, unlike a null result.
    const value = result.categories
        ? result.categories
              .map((key) => evaluation.output_config.options?.find((option) => option.key === key)?.label ?? key)
              .join(', ') || 'No categories'
        : result.score !== null && result.score !== undefined
          ? String(result.score)
          : 'N/A'
    return (
        <Tooltip title={result.error || result.reasoning || undefined}>
            <LemonTag
                size="small"
                type={result.error || passes === false ? 'danger' : passes ? 'success' : 'muted'}
                className="shrink-0 animate-fade-in motion-reduce:animate-none"
            >
                {result.error ? 'Error' : passes === null ? value : passes ? 'Pass' : 'Fail'}
            </LemonTag>
        </Tooltip>
    )
}

function rowTitle(row: EvaluationSampleTrafficItemApi): string {
    return row.input_preview ? `"${row.input_preview}"` : row.sample_id
}

/** A generation row opens on that generation, any other on its trace. */
function drawerRow(row: EvaluationSampleTrafficItemApi, evaluation: EvaluationConfig): TraceListRow | null {
    if (!row.trace_id) {
        return null
    }
    return {
        traceId: row.trace_id,
        timestamp: row.timestamp,
        stepId: evaluation.target === 'generation' ? row.sample_id : row.trace_id,
    }
}

/**
 * A few real runs from the last 7 days that the evaluation would cover, each opening in the trace drawer. Hog code
 * is tested on them as it changes; a judge is tested with a click on the check step.
 */
export function EvaluationTrafficPreview({ testable }: { testable: boolean }): JSX.Element | null {
    const { props } = useMountedLogic(llmEvaluationLogic)
    const logic = evaluationPreviewLogic(props)
    const { evaluation } = useValues(llmEvaluationLogic)
    const { rows, samplesLoading, samplesError, testResults, testResultsLoading, testError } = useValues(logic)
    const { testRows } = useActions(logic)
    const { rowProps } = useTraceDrawerRows(PREVIEW_DRAWER_LIST_ID, TRACE_LINK)
    const drawerRows = useMemo(
        () => (evaluation ? rows.flatMap((row) => drawerRow(row, evaluation) ?? []) : []),
        [rows, evaluation]
    )

    if (!evaluation) {
        return null
    }
    const kind = testableKind(evaluation)
    const unit = evaluation.target
    // A failed run, such as code that no longer compiles, leaves the last results behind, so they stop showing.
    const results = testError ? null : testResults
    const verdicts = rows.flatMap((row) => {
        const result = results?.[row.sample_id]
        return result ? [resultPasses(result, evaluation)] : []
    })
    const graded = verdicts.filter((passes) => passes !== null)
    // Only a judge shows the test button, so it counts the runs a judge test covers.
    const testCount = Math.min(rows.length, JUDGE_TEST_LIMIT)

    return (
        <div className="flex flex-col gap-2" data-attr="llma-evaluation-create-preview">
            <div className="flex items-baseline justify-between gap-2">
                <h4 className="mb-0 text-xs font-semibold">Would run on</h4>
                {verdicts.length > 0 ? (
                    <span
                        className="flex items-center gap-1 text-xs text-secondary"
                        data-attr="llma-evaluation-create-preview-summary"
                    >
                        {kind === 'hog' && (
                            <span className="size-1.5 rounded-full bg-success animate-pulse motion-reduce:animate-none" />
                        )}
                        {/* Each changing number sits in its own element, so page translation can't leave it stale. */}
                        {graded.length > 0 ? (
                            <span
                                key={graded.filter(Boolean).length}
                                className="animate-fade-in motion-reduce:animate-none"
                            >
                                {`${graded.filter(Boolean).length} of ${graded.length} pass`}
                            </span>
                        ) : (
                            <span>{`${pluralize(verdicts.length, 'result')}`}</span>
                        )}
                    </span>
                ) : (
                    <span className="text-xs text-secondary">
                        {kind === 'hog' && testResultsLoading ? 'Testing…' : 'Last 7 days'}
                    </span>
                )}
            </div>
            {samplesLoading && rows.length === 0 ? (
                <LemonSkeleton className="h-6" repeat={3} />
            ) : samplesError ? (
                <p className="mb-0 text-xs text-danger">Couldn't load matching traffic.</p>
            ) : rows.length === 0 ? (
                <p className="mb-0 text-xs text-secondary">{`No ${unit}s matched in the last 7 days.`}</p>
            ) : (
                <ul className="-mx-1.5 m-0 flex list-none flex-col p-0">
                    {rows.map((row, index) => {
                        const result = results?.[row.sample_id]
                        const { className, onClickCapture } = rowProps(drawerRow(row, evaluation))
                        return (
                            <li
                                key={row.sample_id}
                                onClickCapture={onClickCapture}
                                className={`flex items-center gap-2 rounded px-1.5 py-1 hover:bg-fill-highlight-100 animate-fade-in motion-reduce:animate-none ${ROW_STAGGER[Math.min(index, ROW_STAGGER.length - 1)]} ${className ?? ''}`}
                                data-attr="llma-evaluation-create-preview-row"
                            >
                                {row.trace_id ? (
                                    <Link
                                        to={urls.aiObservabilityTrace(row.trace_id, {
                                            event: evaluation.target === 'generation' ? row.sample_id : undefined,
                                            timestamp: row.timestamp ?? undefined,
                                        })}
                                        className={`${TRACE_LINK.slice(1)} min-w-0 flex-1 truncate text-xs`}
                                        subtle
                                    >
                                        {rowTitle(row)}
                                    </Link>
                                ) : (
                                    <span className="min-w-0 flex-1 truncate text-xs">{rowTitle(row)}</span>
                                )}
                                {result ? (
                                    <ResultTag result={result} evaluation={evaluation} />
                                ) : (
                                    <span className="shrink-0 text-xxs text-secondary">
                                        {row.timestamp ? dayjs(row.timestamp).fromNow() : ''}
                                    </span>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}
            {testable && evaluation.evaluation_type === 'llm_judge' && (
                <LemonButton
                    type="primary"
                    size="small"
                    fullWidth
                    center
                    loading={testResultsLoading}
                    onClick={() => testRows({ auto: false })}
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
                    tooltip="Each run is one call on your own API key."
                    data-attr="llma-evaluation-create-preview-test"
                >
                    {testCount > 0 ? `Test on ${pluralize(testCount, unit)}` : 'Test'}
                </LemonButton>
            )}
            {testError && <p className="mb-0 text-xs text-danger">{testError}</p>}
            <TraceDrawerRowsSync listId={PREVIEW_DRAWER_LIST_ID} rows={drawerRows} />
        </div>
    )
}
