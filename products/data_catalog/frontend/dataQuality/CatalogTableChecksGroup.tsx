import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { QuillSubjectRunBanners } from 'products/data_quality/frontend/overview/QuillSubjectRunBanners'

import { ChecksSubject } from '../catalogTableRows'
import { CatalogChecksSummary } from '../components/CatalogChecksSummary'
import { MutedCellText } from '../tables/MutedCellText'
import { catalogDataQualityLogic } from './catalogDataQualityLogic'
import { TableChecksPanel } from './TableChecksPanel'

const CHECKS_RUNNING_REASON = 'Checks are already running'

function checksRegionId(row: ChecksSubject): string {
    return `data-catalog-quality-checks-${row.key}`
}

function RunChecksButton({ row }: { row: ChecksSubject }): JSX.Element | null {
    const { startingRun, isRunning, runningSubjectKey } = useValues(dataQualityOverviewLogic)
    const { runTableChecks } = useActions(catalogDataQualityLogic)
    if (!row.checkGroup) {
        return null
    }
    const running = runningSubjectKey === row.checkGroup.subjectKey
    return (
        <Button
            variant="outline"
            size="sm"
            loading={running}
            disabledReason={(startingRun || isRunning) && !running ? CHECKS_RUNNING_REASON : undefined}
            onClick={() => runTableChecks(row)}
            data-attr="data-catalog-quality-run-table"
        >
            Run checks
        </Button>
    )
}

export function CatalogTableChecksGroup({
    row,
    expanded,
    collapsible,
}: {
    row: ChecksSubject
    expanded: boolean
    collapsible: boolean
}): JSX.Element {
    const { toggleTableExpanded } = useActions(catalogDataQualityLogic)
    return (
        <div className="rounded-md border border-border" data-attr="data-catalog-quality-table">
            <div className="flex flex-wrap items-center gap-2 p-2">
                {collapsible && (
                    <Button
                        size="icon"
                        aria-expanded={expanded}
                        aria-controls={checksRegionId(row)}
                        aria-label={`${expanded ? 'Hide' : 'Show'} checks for ${row.name}`}
                        onClick={() => toggleTableExpanded(row.key)}
                        data-attr="data-catalog-quality-disclosure"
                    >
                        <IconChevronRight
                            aria-hidden
                            className={cn(
                                'transition-transform motion-reduce:transition-none',
                                expanded && 'rotate-90'
                            )}
                        />
                    </Button>
                )}
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
                    {row.detailUrl ? (
                        <Button
                            variant="link"
                            size="inline"
                            className="font-medium text-foreground"
                            render={<LinkPrimitive to={row.detailUrl} />}
                            data-attr="data-catalog-quality-table-name"
                        >
                            {row.name}
                        </Button>
                    ) : (
                        <span className="font-medium">{row.name}</span>
                    )}
                    <MutedCellText>{row.checkGroup ? <CatalogChecksSummary row={row} /> : 'No checks'}</MutedCellText>
                </div>
                <RunChecksButton row={row} />
            </div>
            {row.checkGroup && (
                <div className="flex flex-col gap-2 px-2 pb-2 empty:hidden">
                    <QuillSubjectRunBanners group={row.checkGroup} />
                </div>
            )}
            {expanded && (
                <div id={checksRegionId(row)} className="border-t border-border">
                    <TableChecksPanel row={row} />
                </div>
            )}
        </div>
    )
}
