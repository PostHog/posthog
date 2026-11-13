import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { TraceDrawerRowProps } from '../../redesign/trace/TraceDrawerRowsHost'
import type { EvaluationTarget } from '../types'
import { EvaluationPreviewResultTag } from './EvaluationPreviewResultTag'
import { PREVIEW_TRACE_LINK_CLASS, type PreviewRun, previewSummary } from './previewRuns'

// Rows arrive one after another, so a new filter reads as the traffic changing. Tailwind needs literal classes.
const ROW_STAGGER = [
    '',
    '[animation-delay:60ms]',
    '[animation-delay:120ms]',
    '[animation-delay:180ms]',
    '[animation-delay:240ms]',
    '[animation-delay:300ms]',
]

const SUMMARY_TONES = { success: 'bg-success', danger: 'bg-danger', muted: 'bg-muted' }

export interface EvaluationPreviewRunsProps {
    unit: EvaluationTarget
    runs: PreviewRun[]
    loading: boolean
    loadFailed: boolean
    /** True when filters matched traffic and the sampling percentage left none of it to show. */
    noneInSample: boolean
    live: boolean
    testing: boolean
    rowProps: (run: PreviewRun) => TraceDrawerRowProps
}

export function EvaluationPreviewRuns({
    unit,
    runs,
    loading,
    loadFailed,
    noneInSample,
    live,
    testing,
    rowProps,
}: EvaluationPreviewRunsProps): JSX.Element {
    const summary = loadFailed ? null : previewSummary(runs)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
                <h4 className="mb-0 text-xs font-semibold">Would run on</h4>
                {summary ? (
                    <span
                        className={cn(
                            'flex items-center gap-1 text-xs',
                            summary.tone === 'danger' ? 'text-danger' : 'text-secondary'
                        )}
                        data-attr="llma-evaluation-create-preview-summary"
                    >
                        {live && (
                            <span
                                className={cn(
                                    'size-1.5 rounded-full animate-pulse motion-reduce:animate-none',
                                    SUMMARY_TONES[summary.tone]
                                )}
                            />
                        )}
                        {/* Keyed on the text, so page translation can't leave a stale number behind. */}
                        <span key={summary.text} className="animate-fade-in motion-reduce:animate-none">
                            {summary.text}
                        </span>
                    </span>
                ) : (
                    <span className="text-xs text-secondary">{live && testing ? 'Testing…' : 'Last 7 days'}</span>
                )}
            </div>
            {loading ? (
                <LemonSkeleton className="h-6" repeat={3} />
            ) : loadFailed ? (
                <p className="mb-0 text-xs text-danger">Couldn't load matching traffic.</p>
            ) : runs.length === 0 ? (
                <p className="mb-0 text-xs text-secondary" data-attr="llma-evaluation-create-preview-empty">
                    {noneInSample
                        ? `None of the matching ${unit}s fall in the sample.`
                        : `No ${unit}s matched in the last 7 days.`}
                </p>
            ) : (
                <ul className="-mx-1.5 m-0 flex list-none flex-col p-0">
                    {runs.map((run, index) => {
                        const { className, onClickCapture } = rowProps(run)
                        return (
                            <li
                                key={run.id}
                                onClickCapture={onClickCapture}
                                className={cn(
                                    'flex items-center gap-2 rounded px-1.5 py-1 hover:bg-fill-highlight-100 animate-fade-in motion-reduce:animate-none',
                                    ROW_STAGGER[Math.min(index, ROW_STAGGER.length - 1)],
                                    className
                                )}
                                data-attr="llma-evaluation-create-preview-row"
                            >
                                {run.href ? (
                                    <Link
                                        to={run.href}
                                        // A plain click opens the drawer. Without the drawer it opens a tab, so the
                                        // draft is still there afterwards.
                                        target="_blank"
                                        targetBlankIcon={false}
                                        className={cn(PREVIEW_TRACE_LINK_CLASS, 'min-w-0 flex-1 truncate text-xs')}
                                        subtle
                                    >
                                        {run.title}
                                    </Link>
                                ) : (
                                    <span className="min-w-0 flex-1 truncate text-xs">{run.title}</span>
                                )}
                                {run.result ? (
                                    <EvaluationPreviewResultTag result={run.result} />
                                ) : (
                                    <span className="shrink-0 text-xxs text-secondary">
                                        {run.timestamp ? dayjs(run.timestamp).fromNow() : ''}
                                    </span>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}
            {summary?.error && (
                <p className="mb-0 break-words text-xs text-danger" data-attr="llma-evaluation-create-preview-error">
                    {summary.error}
                </p>
            )}
        </div>
    )
}
