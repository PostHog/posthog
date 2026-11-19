import clsx from 'clsx'

import type { SessionListItemApi, TracePersonApi, TracePreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { formatCostUsd, formatLatencyMs } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import { TracePersonCell } from '../../traces/components/TracePersonCell'

export interface SessionListRowProps {
    item: SessionListItemApi
    title: TraceCellLoad<TracePreviewApi>
    person: TraceCellLoad<TracePersonApi | null>
    isOpen: boolean
}

function turnsLabel(turnCount: number): string {
    return turnCount === 1 ? '1 turn' : `${turnCount} turns`
}

function Title({ title }: { title: SessionListRowProps['title'] }): JSX.Element {
    const text = title.status === 'ready' ? title.value.input : null
    return (
        <TraceCellValue status={title.status} skeletonWidth="w-48">
            {/* The title is the customer's first prompt, so autocapture must not record it. */}
            <div
                title={text ?? undefined}
                className={clsx('ph-no-capture truncate font-medium', !text && 'text-muted')}
            >
                {text ?? 'Untitled session'}
            </div>
        </TraceCellValue>
    )
}

export function SessionListRow({ item, title, person, isOpen }: SessionListRowProps): JSX.Element {
    const { durationMs, totals, turnCount, lastSeen } = item
    const facts = [
        turnsLabel(turnCount),
        durationMs !== null ? formatLatencyMs(durationMs) : null,
        totals.costUsd !== null ? formatCostUsd(totals.costUsd) : null,
    ].filter((fact): fact is string => fact !== null)

    return (
        <div
            className={clsx('flex flex-col gap-1 px-3 py-2', isOpen && 'bg-fill-highlight-100')}
            aria-current={isOpen ? 'true' : undefined}
            data-attr="ai-observability-session-row"
        >
            <Title title={title} />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                <TracePersonCell person={person.status === 'ready' ? person.value : null} status={person.status} />
                <span>{facts.join(' · ')}</span>
                <span className="ml-auto">
                    <ShortTimestamp time={lastSeen} />
                </span>
            </div>
        </div>
    )
}
