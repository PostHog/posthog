import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    Badge,
    Button,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { SUITE_RUN_STATUS_BADGE_VARIANTS } from './checkBadgeVariants'
import { NARROW_ONLY, SKELETON_ROW_COUNT, WIDE_ONLY_CELL } from './checkTableLayout'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import type { DataQualitySuiteRunApi } from './generated/api.schemas'
import { QuillCheckRunsTable } from './QuillCheckRunsTable'
import { QuillRowExpandButton } from './QuillRowExpandButton'
import { useExpandedRowIds } from './useExpandedRowIds'

const COLUMN_COUNT = 6
const EMPTY_VALUE = '-'

function suiteRunDuration(suiteRun: DataQualitySuiteRunApi): string {
    if (!suiteRun.started_at || !suiteRun.finished_at) {
        return EMPTY_VALUE
    }
    const seconds = (new Date(suiteRun.finished_at).getTime() - new Date(suiteRun.started_at).getTime()) / 1000
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}

function suiteRunOutcome(suiteRun: DataQualitySuiteRunApi): string {
    return `${suiteRun.checks_passed} passed, ${suiteRun.checks_failed} failed, ${suiteRun.checks_errored} errored, ${suiteRun.checks_skipped} skipped`
}

function SuiteRunStatus({ suiteRun }: { suiteRun: DataQualitySuiteRunApi }): JSX.Element {
    return (
        <Badge variant={SUITE_RUN_STATUS_BADGE_VARIANTS[suiteRun.status] ?? 'default'}>
            {suiteRun.status === 'empty' ? 'No checks matched' : suiteRun.status}
        </Badge>
    )
}

function SuiteRunRows({
    suiteRun,
    expanded,
    onToggle,
    logicProps,
}: {
    suiteRun: DataQualitySuiteRunApi
    expanded: boolean
    onToggle: () => void
    logicProps: DataQualityChecksLogicProps
}): JSX.Element {
    const { suiteRunCheckRunsBySuiteRunId, pendingCheckActions } = useValues(dataQualityChecksLogic(logicProps))

    return (
        <>
            <TableRow>
                <TableCell valign="top" className="w-0 pr-0">
                    <QuillRowExpandButton
                        expanded={expanded}
                        label={`${expanded ? 'Hide' : 'Show'} check results for this run`}
                        onToggle={onToggle}
                        dataAttr="data-quality-suite-run-expand"
                    />
                </TableCell>
                <TableCell valign="top">
                    <div className="flex flex-col items-start gap-1">
                        <SuiteRunStatus suiteRun={suiteRun} />
                        <Text size="xs" variant="muted" className={cn(NARROW_ONLY, 'm-0')}>
                            {suiteRunOutcome(suiteRun)}
                        </Text>
                    </div>
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    {suiteRun.trigger}
                </TableCell>
                <TableCell valign="top">
                    {suiteRun.started_at ? <TZLabel time={suiteRun.started_at} /> : EMPTY_VALUE}
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    {suiteRunDuration(suiteRun)}
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    {suiteRunOutcome(suiteRun)}
                </TableCell>
            </TableRow>
            {expanded && (
                <TableRow>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <QuillCheckRunsTable
                            runs={suiteRunCheckRunsBySuiteRunId[suiteRun.id] ?? []}
                            loading={pendingCheckActions.loadingSuiteRunRuns[suiteRun.id]}
                            showCheck
                        />
                    </TableCell>
                </TableRow>
            )}
        </>
    )
}

export function QuillSuiteRunsHistory(props: DataQualityChecksLogicProps): JSX.Element {
    const logic = dataQualityChecksLogic(props)
    const { suiteRuns, suiteRunsLoading, suiteRunsError } = useValues(logic)
    const { loadSuiteRuns, loadSuiteRunCheckRuns } = useActions(logic)
    const expandedRows = useExpandedRowIds(loadSuiteRunCheckRuns)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <Button
                    size="icon"
                    loading={suiteRunsLoading}
                    onClick={loadSuiteRuns}
                    tooltip="Refresh check run history"
                    aria-label="Refresh check run history"
                    data-attr="data-quality-suite-runs-refresh"
                >
                    <IconRefresh />
                </Button>
            </div>
            <Table fullWidth size="sm" aria-busy={suiteRunsLoading || undefined}>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-0 pr-0">
                            <span className="sr-only">Check results</span>
                        </TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Trigger</TableHead>
                        <TableHead>Started</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Duration</TableHead>
                        <TableHead className={WIDE_ONLY_CELL}>Outcome</TableHead>
                    </TableRow>
                </TableHeader>
                {suiteRunsLoading && suiteRuns.length === 0 ? (
                    <TableBody>
                        {Array.from({ length: SKELETON_ROW_COUNT }, (_, index) => (
                            <TableRow key={index}>
                                <TableCell colSpan={COLUMN_COUNT}>
                                    <Skeleton className="h-5 w-full" />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                ) : suiteRuns.length === 0 ? (
                    <TableEmpty>
                        <Text size="xs" variant="muted">
                            {suiteRunsError
                                ? "Couldn't load the run history. Refresh to try again."
                                : 'No check runs yet. Run all checks to see results here.'}
                        </Text>
                    </TableEmpty>
                ) : (
                    <TableBody>
                        {suiteRuns.map((suiteRun) => (
                            <SuiteRunRows
                                key={suiteRun.id}
                                suiteRun={suiteRun}
                                expanded={expandedRows.isExpanded(suiteRun.id)}
                                onToggle={() => expandedRows.toggle(suiteRun.id)}
                                logicProps={props}
                            />
                        ))}
                    </TableBody>
                )}
            </Table>
        </div>
    )
}
