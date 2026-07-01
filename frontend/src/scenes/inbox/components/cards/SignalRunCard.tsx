import clsx from 'clsx'

import { LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { SignalRun } from '../../types'
import { stripScoutPrefix } from '../../utils/scoutRunsWindow'
import { RunStatusOrb, resolveRunVariant, VARIANT_META } from './runStatusVariant'

export function SignalRunCard({ run }: { run: SignalRun }): JSX.Element {
    const variant = resolveRunVariant(run.status)
    const meta = VARIANT_META[variant]
    // Kind chip makes scout-vs-signal unambiguous at a glance.
    const isScout = run.kind === 'scout'
    const kindBadgeType: LemonTagType = isScout ? 'completion' : 'option'
    // Scout titles are skill code names — strip the common prefix and show verbatim in monospace
    // (they're identifiers, not prose). Signal titles are the originating report's title.
    const displayTitle = isScout ? stripScoutPrefix(run.title) : run.title

    return (
        <Link
            to={urls.taskDetail(run.task_id)}
            className="group flex w-full items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-3.5 text-left text-inherit no-underline transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <RunStatusOrb meta={meta} />

            <div className="flex flex-col gap-1 min-w-0 flex-1">
                <div className="flex items-center gap-2 min-w-0">
                    <LemonTag size="small" type={kindBadgeType} className="shrink-0 select-none">
                        {isScout ? 'Scout' : 'Signal'}
                    </LemonTag>
                    <span
                        className={clsx(
                            'truncate min-w-0 text-sm leading-snug',
                            isScout ? 'font-mono text-[13px]' : 'font-semibold tracking-tight'
                        )}
                    >
                        {displayTitle || 'Untitled run'}
                    </span>
                </div>
                <span className="text-xs text-tertiary leading-none select-none">
                    <TZLabel time={run.created_at} />
                </span>
            </div>

            <div className="flex flex-col items-end justify-center gap-1.5 self-stretch shrink-0 border-l border-primary pl-3">
                <LemonTag size="small" type={meta.badgeType} className="select-none">
                    {meta.label}
                </LemonTag>
            </div>
        </Link>
    )
}
