import { Dot, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { DataModelingJobStatus } from '~/types'

import { subjectSince } from 'products/data_modeling/frontend/overviewIssueCopy'

import { CatalogTableRow, TableKind } from '../catalogTableRows'
import { MutedCellText } from './MutedCellText'

const RUN_HISTORY_LENGTH = 5

const NO_REFRESH_LABELS: Record<TableKind, string> = {
    posthog: 'Managed by PostHog',
    source: 'Not synced yet',
    self_managed: 'Queried in place',
    view: 'Runs on read',
    materialized_view: 'Never run',
}

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

function RefreshTime({ row }: { row: CatalogTableRow }): JSX.Element {
    const since = row.health.materialization?.kind === 'behind' ? subjectSince(row.health) : null
    return (
        <MutedCellText>
            {since?.kind === 'overdue' ? (
                since.label
            ) : row.refreshedAt ? (
                <TZLabel time={row.refreshedAt} />
            ) : (
                NO_REFRESH_LABELS[row.kind]
            )}
        </MutedCellText>
    )
}

export function CatalogTableRefresh({ row }: { row: CatalogTableRow }): JSX.Element {
    if (row.kind === 'posthog' || row.kind === 'self_managed' || row.kind === 'view') {
        return <MutedCellText>{NO_REFRESH_LABELS[row.kind]}</MutedCellText>
    }
    return (
        <div className="flex flex-col gap-1">
            <RunDots row={row} />
            <RefreshTime row={row} />
        </div>
    )
}
