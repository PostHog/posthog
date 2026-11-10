import { useActions, useValues } from 'kea'

import {
    Badge,
    Skeleton,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { SEVERITY_BADGE_VARIANTS } from './checkBadgeVariants'
import { checkDisplayName } from './checksConstants'
import { NARROW_ONLY, SKELETON_ROW_COUNT, WIDE_ONLY_CELL } from './checkTableLayout'
import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import type { DataQualityCheckApi, DataQualityOutputColumnApi } from './generated/api.schemas'
import { QuillCheckDefinitionCells } from './QuillCheckDefinitionCells'
import { QuillCheckLastRunCells } from './QuillCheckLastRunCells'
import { QuillCheckRowMenu } from './QuillCheckRowMenu'
import { QuillCheckRunsRow } from './QuillCheckRunsRow'
import { QuillCheckStatusCell } from './QuillCheckStatusCell'
import { QuillRowExpandButton } from './QuillRowExpandButton'
import { useExpandedRowIds } from './useExpandedRowIds'

const COLUMN_COUNT = 9
const DEFAULT_SEVERITY = 'error'

function aiTooltip(check: DataQualityCheckApi): string {
    const confidence =
        check.confidence !== null && check.confidence !== undefined ? `${check.confidence} confidence` : ''
    return [confidence, check.reasoning].filter(Boolean).join('. ') || 'Written by an agent'
}

function SeverityBadge({ check }: { check: DataQualityCheckApi }): JSX.Element {
    const severity = check.severity ?? DEFAULT_SEVERITY
    return <Badge variant={SEVERITY_BADGE_VARIANTS[severity] ?? 'default'}>{severity}</Badge>
}

function NameCell({ check }: { check: DataQualityCheckApi }): JSX.Element {
    const name = checkDisplayName(check)
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
                {check.description ? (
                    <Tooltip>
                        <TooltipTrigger render={<span className="font-medium" />}>{name}</TooltipTrigger>
                        <TooltipContent>{check.description}</TooltipContent>
                    </Tooltip>
                ) : (
                    <span className="font-medium">{name}</span>
                )}
                {check.created_source === 'ai_generated' && (
                    <Tooltip>
                        <TooltipTrigger render={<Badge variant="completed" />}>AI</TooltipTrigger>
                        <TooltipContent>{aiTooltip(check)}</TooltipContent>
                    </Tooltip>
                )}
                {check.owner && (
                    <Text size="xs" variant="muted" render={<span />}>
                        {check.owner}
                    </Text>
                )}
            </div>
            <div className={cn(NARROW_ONLY, 'flex flex-col items-start gap-1')}>
                {check.name && (
                    <Text size="xs" variant="muted" className="m-0">
                        {checkDisplayName({ ...check, name: '' })}
                    </Text>
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge check={check} />
                    <QuillCheckStatusCell check={check} />
                </div>
            </div>
        </div>
    )
}

function CheckRows({
    check,
    expanded,
    onToggle,
    logicProps,
    columns,
    outputSchema,
}: {
    check: DataQualityCheckApi
    expanded: boolean
    onToggle: () => void
    logicProps: DataQualityChecksLogicProps
    columns: string[]
    outputSchema: DataQualityOutputColumnApi[]
}): JSX.Element {
    const logic = dataQualityChecksLogic(logicProps)
    const { pendingCheckActions, checkRunsByCheckId } = useValues(logic)
    const { deleteCheck, toggleCheckEnabled, runCheck, openFailingRows } = useActions(logic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)
    const name = checkDisplayName(check)

    return (
        <>
            <TableRow data-attr="data-quality-check-row">
                <TableCell valign="top" className="w-0 pr-0">
                    <QuillRowExpandButton
                        expanded={expanded}
                        label={`${expanded ? 'Hide' : 'Show'} runs for ${name}`}
                        onToggle={onToggle}
                        dataAttr="data-quality-check-expand"
                    />
                </TableCell>
                <TableCell expand valign="top">
                    <NameCell check={check} />
                </TableCell>
                <QuillCheckDefinitionCells check={check} />
                <TableCell valign="top" className={WIDE_ONLY_CELL}>
                    <SeverityBadge check={check} />
                </TableCell>
                <TableCell valign="top">
                    <Switch
                        checked={check.enabled !== false}
                        onCheckedChange={(enabled: boolean) => toggleCheckEnabled(check.id, enabled)}
                        disabledReason={pendingCheckActions.toggling[check.id] ? 'Saving' : undefined}
                        aria-label={`Enable check ${name}`}
                        data-attr="data-quality-check-enabled"
                    />
                </TableCell>
                <QuillCheckLastRunCells check={check} />
                <TableCell valign="top" align="right" className="w-0">
                    <QuillCheckRowMenu
                        checkName={name}
                        dataAttr="data-quality-check-actions"
                        onRunNow={() => runCheck(check.id)}
                        runDisabledReason={
                            pendingCheckActions.running[check.id] ? 'This check is already starting' : undefined
                        }
                        onEdit={() => openEditor(check, logicProps, columns, outputSchema)}
                        onOpenFailingRows={() => openFailingRows(check.id)}
                        onDelete={() => deleteCheck(check.id)}
                        deleteDisabledReason={
                            pendingCheckActions.deleting[check.id] ? 'This check is being deleted' : undefined
                        }
                    />
                </TableCell>
            </TableRow>
            {expanded && (
                <QuillCheckRunsRow
                    colSpan={COLUMN_COUNT}
                    description={check.description}
                    runs={checkRunsByCheckId[check.id] ?? []}
                    loading={pendingCheckActions.loadingRuns[check.id]}
                />
            )}
        </>
    )
}

export interface QuillChecksTableProps extends DataQualityChecksLogicProps {
    columns: string[]
    outputSchema: DataQualityOutputColumnApi[]
}

export function QuillChecksTable({ columns, outputSchema, ...logicProps }: QuillChecksTableProps): JSX.Element {
    const logic = dataQualityChecksLogic(logicProps)
    const { sortedChecks, checksLoading } = useValues(logic)
    const { loadCheckRuns } = useActions(logic)
    const expandedRows = useExpandedRowIds(loadCheckRuns)

    return (
        <Table fullWidth size="sm" aria-busy={checksLoading || undefined} data-attr="data-quality-checks-table">
            <TableHeader>
                <TableRow>
                    <TableHead className="w-0 pr-0">
                        <span className="sr-only">Runs</span>
                    </TableHead>
                    <TableHead expand>Name</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Type</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Column</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Severity</TableHead>
                    <TableHead>Enabled</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>Last status</TableHead>
                    <TableHead className={WIDE_ONLY_CELL}>
                        <Tooltip>
                            <TooltipTrigger render={<span />}>Last run</TooltipTrigger>
                            <TooltipContent>When the check last ran, not when the data was last synced.</TooltipContent>
                        </Tooltip>
                    </TableHead>
                    <TableHead className="w-0">
                        <span className="sr-only">Actions</span>
                    </TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {checksLoading && sortedChecks.length === 0
                    ? Array.from({ length: SKELETON_ROW_COUNT }, (_, index) => (
                          <TableRow key={index}>
                              <TableCell colSpan={COLUMN_COUNT}>
                                  <Skeleton className="h-6 w-full" />
                              </TableCell>
                          </TableRow>
                      ))
                    : sortedChecks.map((check) => (
                          <CheckRows
                              key={check.id}
                              check={check}
                              expanded={expandedRows.isExpanded(check.id)}
                              onToggle={() => expandedRows.toggle(check.id)}
                              logicProps={logicProps}
                              columns={columns}
                              outputSchema={outputSchema}
                          />
                      ))}
            </TableBody>
        </Table>
    )
}
