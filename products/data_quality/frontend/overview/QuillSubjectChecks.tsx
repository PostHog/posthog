import { useActions, useValues } from 'kea'

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text, cn } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { checkDisplayName, checkTypeLabel } from '../checksConstants'
import { NARROW_ONLY, WIDE_ONLY_CELL } from '../checkTableLayout'
import { dataQualityCheckEditorLogic } from '../dataQualityCheckEditorLogic'
import type { DataQualityOverviewCheckApi } from '../generated/api.schemas'
import { QuillCheckRowMenu } from '../QuillCheckRowMenu'
import { QuillCheckRunsTable } from '../QuillCheckRunsTable'
import { QuillCheckStatusCell } from '../QuillCheckStatusCell'
import { QuillRowExpandButton } from '../QuillRowExpandButton'
import { useExpandedRowIds } from '../useExpandedRowIds'
import {
    SubjectGroup,
    dataQualityOverviewLogic,
    focusCandidatesAfterDelete,
    rowActionsId,
} from './dataQualityOverviewLogic'
import { focusFirstAvailable } from './focusFirstAvailable'

const COLUMN_COUNT = 7
const EMPTY_VALUE = '-'

function CheckRows({
    check,
    group,
    expanded,
    onToggle,
}: {
    check: DataQualityOverviewCheckApi
    group: SubjectGroup
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    const { checkRunsByCheckId, runsLoadingByCheckId, deletingCheckIds, subjectGroups, startingRun, isRunning } =
        useValues(dataQualityOverviewLogic)
    const { deleteCheck, setLastActionCheck, openFailingRows, runChecks } = useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)
    const name = checkDisplayName(check)

    return (
        <>
            <TableRow data-attr="data-quality-overview-check-row">
                <TableCell valign="top" className="w-0 pr-0">
                    <QuillRowExpandButton
                        expanded={expanded}
                        label={`${expanded ? 'Hide' : 'Show'} runs for ${name}`}
                        onToggle={onToggle}
                        dataAttr="data-quality-overview-check-expand"
                    />
                </TableCell>
                <TableCell expand valign="top">
                    <div className="flex min-w-0 flex-col gap-1">
                        <span className="font-medium">{name}</span>
                        <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                            {check.name && (
                                <Text size="xs" variant="muted" className="m-0">
                                    {checkDisplayName({ ...check, name: '' })}
                                </Text>
                            )}
                            <QuillCheckStatusCell check={check} />
                        </div>
                    </div>
                </TableCell>
                <TableCell valign="top" className={cn(WIDE_ONLY_CELL, 'whitespace-nowrap')}>
                    {checkTypeLabel(check.check_type)}
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    {check.column_name || EMPTY_VALUE}
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <QuillCheckStatusCell check={check} />
                </TableCell>
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    {check.last_run_at ? <TZLabel time={check.last_run_at} /> : EMPTY_VALUE}
                </TableCell>
                <TableCell valign="top" align="right" className="w-0">
                    <QuillCheckRowMenu
                        checkName={name}
                        triggerId={rowActionsId(check.id)}
                        dataAttr="data-quality-overview-check-actions"
                        onRunNow={() => runChecks({ kind: 'subject', subjectKey: group.subjectKey }, [check.id])}
                        runDisabledReason={startingRun || isRunning ? 'Checks are already running' : undefined}
                        onEdit={() => {
                            setLastActionCheck(check.id)
                            openEditor(check, { subjectType: check.subject_type, subjectId: check.subject_uuid ?? '' })
                        }}
                        onOpenFailingRows={() => openFailingRows(check)}
                        onDelete={() => {
                            const fallbacks = focusCandidatesAfterDelete(subjectGroups, group.subjectKey, check.id)
                            deleteCheck(check)
                            focusFirstAvailable(fallbacks)
                        }}
                        onDeleteCancelled={() => focusFirstAvailable([rowActionsId(check.id)])}
                        deleteDisabledReason={deletingCheckIds[check.id] ? 'This check is being deleted' : undefined}
                    />
                </TableCell>
            </TableRow>
            {expanded && (
                <TableRow>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <div className="flex flex-col gap-2">
                            {check.description && (
                                <Text size="xs" variant="muted" className="m-0">
                                    {check.description}
                                </Text>
                            )}
                            <QuillCheckRunsTable
                                runs={checkRunsByCheckId[check.id] ?? []}
                                loading={runsLoadingByCheckId[check.id]}
                            />
                        </div>
                    </TableCell>
                </TableRow>
            )}
        </>
    )
}

export function QuillSubjectChecks({ group }: { group: SubjectGroup }): JSX.Element {
    const { loadCheckRuns } = useActions(dataQualityOverviewLogic)
    const checksById = new Map(group.checks.map((check) => [check.id, check]))
    const expandedRows = useExpandedRowIds((checkId) => {
        const check = checksById.get(checkId)
        if (check) {
            loadCheckRuns(check)
        }
    })

    return (
        <Table fullWidth size="sm" data-attr="data-quality-overview-checks-table">
            <TableHeader>
                <TableRow>
                    <TableHead className="w-0 pr-0">
                        <span className="sr-only">Runs</span>
                    </TableHead>
                    <TableHead expand>Check</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Type</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Column</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Last status</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Last run</TableHead>
                    <TableHead className="w-0">
                        <span className="sr-only">Actions</span>
                    </TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {group.checks.map((check) => (
                    <CheckRows
                        key={check.id}
                        check={check}
                        group={group}
                        expanded={expandedRows.isExpanded(check.id)}
                        onToggle={() => expandedRows.toggle(check.id)}
                    />
                ))}
            </TableBody>
        </Table>
    )
}
