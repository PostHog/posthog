import { pluralize } from 'lib/utils/strings'

import { urls } from '~/scenes/urls'

import { getEvaluationResultDisplay } from '../../components/EvaluationResultTag'
import type {
    EvaluationSampleTrafficItemApi,
    PreviewOutcomeEnumApi,
    TestHogResultItemApi,
} from '../../generated/api.schemas'
import type { TraceListRow } from '../../redesign/trace/traceListRows'
import { resultOutcome } from '../evaluationPreviewLogic'
import type { EvaluationConfig, EvaluationTarget } from '../types'

/** The drawer host renders outside the sticky preview panel, whose stacking context would trap it under the page. */
export const PREVIEW_DRAWER_LIST_ID = 'evaluation-preview'
export const PREVIEW_TRACE_LINK_CLASS = 'llma-evaluation-preview-trace-link'

export interface PreviewRunResult {
    /** Null when the evaluation has no rule to grade the result, such as a score with no passing rule. */
    outcome: PreviewOutcomeEnumApi | null
    value: string
    detail: string | null
}

export interface PreviewRun {
    id: string
    title: string
    href: string | null
    timestamp: string | null
    result: PreviewRunResult | null
    drawerRow: TraceListRow | null
}

/** A generation run opens on that generation, any other on its trace. */
function drawerRow(row: EvaluationSampleTrafficItemApi, target: EvaluationTarget): TraceListRow | null {
    if (!row.trace_id) {
        return null
    }
    return {
        traceId: row.trace_id,
        timestamp: row.timestamp,
        stepId: target === 'generation' ? row.sample_id : row.trace_id,
    }
}

function runResult(result: TestHogResultItemApi, evaluation: EvaluationConfig): PreviewRunResult {
    return {
        outcome: resultOutcome(result, evaluation),
        value: getEvaluationResultDisplay(
            {
                status: 'completed',
                result: result.result,
                result_type: evaluation.output_type,
                evaluation_type: evaluation.evaluation_type,
                categories: result.categories,
                score: result.score,
            },
            { categoryOptions: evaluation.output_config.options }
        ).label,
        detail: result.error || result.reasoning || null,
    }
}

export function previewRuns(
    rows: EvaluationSampleTrafficItemApi[],
    results: Record<string, TestHogResultItemApi> | null,
    evaluation: EvaluationConfig
): PreviewRun[] {
    return rows.map((row) => {
        const result = results?.[row.sample_id]
        return {
            id: row.sample_id,
            // A run with no text input, such as a tool-only step, has nothing to quote.
            title: row.input_preview ? `"${row.input_preview}"` : 'No input',
            href: row.trace_id
                ? urls.aiObservabilityTrace(row.trace_id, {
                      event: evaluation.target === 'generation' ? row.sample_id : undefined,
                      timestamp: row.timestamp ?? undefined,
                  })
                : null,
            timestamp: row.timestamp ?? null,
            result: result ? runResult(result, evaluation) : null,
            drawerRow: drawerRow(row, evaluation.target),
        }
    })
}

export interface PreviewSummary {
    text: string
    tone: 'success' | 'danger' | 'muted'
    /** Set when every tested run failed the same way a first look can explain, such as a typo in a global. */
    error: string | null
}

export function previewSummary(runs: PreviewRun[]): PreviewSummary | null {
    const results = runs.flatMap((run) => (run.result ? [run.result] : []))
    if (results.length === 0) {
        return null
    }
    const passed = results.filter((result) => result.outcome === 'pass').length
    const graded = passed + results.filter((result) => result.outcome === 'fail').length
    const errors = results.filter((result) => result.outcome === 'error')
    if (errors.length === results.length) {
        return { text: pluralize(errors.length, 'error'), tone: 'danger', error: errors[0].detail }
    }
    const errorText = errors.length > 0 ? `, ${pluralize(errors.length, 'error')}` : ''
    if (graded === 0) {
        return {
            text: `${pluralize(results.length - errors.length, 'result')}${errorText}`,
            tone: 'muted',
            error: null,
        }
    }
    return {
        text: `${passed} of ${graded} pass${errorText}`,
        tone: passed > 0 ? 'success' : 'danger',
        error: null,
    }
}
