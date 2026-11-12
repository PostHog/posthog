import { Dot, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { DataModelingJobStatus } from '~/types'

import { CatalogTableRow } from '../catalogTableRows'
import { MutedCellText } from './MutedCellText'

const RUN_HISTORY_LENGTH = 5

const RUN_DOT_VARIANTS: Record<DataModelingJobStatus, 'success' | 'destructive' | 'warning' | 'default'> = {
    Completed: 'success',
    Failed: 'destructive',
    Running: 'warning',
    Cancelled: 'default',
    Skipped: 'default',
}

function RunDots({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const runs = row.savedQuery?.run_history?.slice(0, RUN_HISTORY_LENGTH).reverse() ?? []
    if (runs.length === 0) {
        return null
    }
    return (
        <span className="flex gap-0.5" aria-label="Recent runs, oldest first">
            {runs.map((run, index) => (
                <Tooltip key={index}>
                    <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                        <Dot variant={RUN_DOT_VARIANTS[run.status] ?? 'default'} />
                    </TooltipTrigger>
                    <TooltipContent>
                        {run.timestamp ? `${run.status}, ${humanFriendlyDetailedTime(run.timestamp)}` : run.status}
                    </TooltipContent>
                </Tooltip>
            ))}
        </span>
    )
}

function FreshnessText({ row }: { row: CatalogTableRow }): JSX.Element {
    const { state, timeLabel, time } = row.freshness
    return (
        <div className="flex flex-col">
            {state && <MutedCellText>{state}</MutedCellText>}
            {time && (
                <MutedCellText>
                    {timeLabel && `${timeLabel} `}
                    <TZLabel time={time} />
                </MutedCellText>
            )}
        </div>
    )
}

export function CatalogTableFreshness({ row }: { row: CatalogTableRow }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            {row.kind === 'materialized_view' && <RunDots row={row} />}
            <FreshnessText row={row} />
        </div>
    )
}
