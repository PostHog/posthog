import type { ReactNode } from 'react'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import type { EvaluationReportRun } from '../types'
import { ReportSectionContent } from './EvaluationReportViewer'

/** A report's title and first section, with the caller's button to open the whole report. */
export function LatestReportPreview({
    run,
    action,
    className,
    summaryClassName,
}: {
    run: EvaluationReportRun
    action: ReactNode
    className?: string
    summaryClassName?: string
}): JSX.Element {
    const [summary] = run.content.sections ?? []
    return (
        <section className={cn('flex flex-col gap-2 rounded border bg-surface-primary', className)}>
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-xs text-secondary">
                        Latest report, <TZLabel time={run.created_at} noStyles />
                    </span>
                    <h3 className="mb-0 text-sm font-semibold">{run.content.title || 'Evaluation report'}</h3>
                </div>
                {action}
            </div>
            {summary?.content && (
                <div className={summaryClassName}>
                    <ReportSectionContent section={summary} citations={run.content.citations ?? []} />
                </div>
            )}
        </section>
    )
}
