import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { IconChevronDown, IconRefresh, IconRevert, IconSearch, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonDropdown,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagProps,
    Tooltip,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { escapeHogQLString, hogql } from '~/queries/utils'
import { DateMappingOption } from '~/types'

import { LogsViewer } from '../logs/LogsViewer'
import { LogsViewerLogicProps } from '../logs/logsViewerLogic'
import { renderHogFunctionMessage } from '../logs/renderHogFunctionMessage'
import {
    BulkRerunParams,
    HOG_INVOCATIONS_RERUN_MAX_COUNT,
    HogInvocationRow,
    HogInvocationsFilters,
    HogInvocationsFunctionKind,
    HogInvocationsLogicProps,
    RunStatus,
    dateClauseFor,
    hogInvocationsLogic,
    isRerunWrapperKind,
} from './hogInvocationsLogic'
import { InvocationsSparkline } from './InvocationsSparkline'
import { InvocationsBetaBanner } from './InvocationsTabBanners'

const STATUS_OPTIONS: { value: RunStatus; label: string }[] = [
    { value: 'running', label: 'Running' },
    { value: 'succeeded', label: 'Succeeded' },
    { value: 'failed', label: 'Failed' },
]

/**
 * Preset windows mirroring the Logs viewer — covers minute-level scoping
 * (5m / 30m / 1h) plus the longer windows the table already supported.
 * Pairs with `allowTimePrecision` + `allowFixedRangeWithTime` so custom
 * ranges accept minute-precision timestamps.
 */
const INVOCATIONS_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date) => date.subtract(5, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date) => date.subtract(30, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(1, 'h'), date),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 4 hours',
        values: ['-4h'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(4, 'h'), date),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

const tagTypeForStatus = (status: RunStatus): LemonTagProps['type'] => {
    switch (status) {
        case 'succeeded':
            return 'success'
        case 'failed':
            return 'danger'
        case 'running':
        default:
            return 'warning'
    }
}

const formatDurationMs = (ms: number | null): string => {
    if (ms === null || ms === undefined) {
        return '—'
    }
    if (ms < 1000) {
        return `${ms} ms`
    }
    return `${(ms / 1000).toFixed(2)} s`
}

const shortId = (id: string): string =>
    id
        .split('-')
        .map((p) => p.slice(0, 2))
        .join('')

const UUID_REGEX = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i
const shortPersonDisplay = (row: { person_id: string; distinct_id: string }): string => {
    const candidate = row.distinct_id || row.person_id || ''
    if (UUID_REGEX.test(candidate)) {
        return `${candidate.slice(0, 4)}…${candidate.slice(-4)}`
    }
    return candidate
}

const rowRibbonColorFor = (row: HogInvocationRow): string | null => {
    if (isRerunWrapperKind(row.function_kind)) {
        return 'var(--info)'
    }
    if (row.status === 'failed') {
        return 'var(--danger)'
    }
    if (row.status === 'running') {
        return 'var(--warning)'
    }
    if (row.status === 'succeeded') {
        return 'var(--success)'
    }
    return null
}

/**
 * Live count for the re-run modal — mirrors the worker's predicate shape
 * (window + status + error_kind + max_attempts) but skips `max_count`
 * (server-side ceiling, not a row filter).
 */
async function countRerunMatches(
    props: { id: string; functionKind: HogInvocationsFunctionKind },
    params: BulkRerunParams
): Promise<number> {
    const statusClause = params.status?.length
        ? hogql.raw(`AND status IN (${params.status.map(escapeHogQLString).join(',')})`)
        : hogql.raw('')
    const errorKindClause = params.error_kind?.length
        ? hogql.raw(`AND error_kind IN (${params.error_kind.map(escapeHogQLString).join(',')})`)
        : hogql.raw('')
    const maxAttemptsClause =
        typeof params.max_attempts === 'number' ? hogql.raw(`AND attempts < ${params.max_attempts}`) : hogql.raw('')
    // Reuse the same inline date clause shape the list / sparkline use.
    const dateClause = dateClauseFor({
        date_from: params.date_from,
        date_to: params.date_to,
    } as HogInvocationsFilters)

    const query = hogql`
        SELECT count() FROM (
            SELECT
                invocation_id,
                argMax(status, version)     AS status,
                argMax(error_kind, version) AS error_kind,
                max(attempts)               AS attempts
            FROM posthog.hog_invocation_results
            WHERE function_kind = ${props.functionKind}
              AND function_id = ${props.id}
              ${dateClause}
            GROUP BY invocation_id
            HAVING argMax(is_deleted, version) = 0
               ${statusClause}
               ${errorKindClause}
               ${maxAttemptsClause}
        )
    `
    const response = await api.queryHogQL(query, {
        scene: 'HogInvocations',
        productKey: 'pipeline_destinations',
    })
    const row = response.results?.[0]
    return Array.isArray(row) ? Number(row[0] ?? 0) : 0
}

export interface HogInvocationsProps extends HogInvocationsLogicProps {
    /**
     * Override how a log message is rendered in the per-row expansion. Workflows
     * pass `renderWorkflowLogMessage` so event/person/action tokens become links,
     * matching the standalone Logs tab. Defaults to the hog-function renderer.
     */
    renderLogMessage?: (message: string) => JSX.Element | string
}

/**
 * Rerun is async — posting to `/rerun` enqueues a cyclotron wrapper job; new
 * lifecycle rows show up here once the worker drains it.
 */
export function HogInvocations({ id, functionKind, renderLogMessage }: HogInvocationsProps): JSX.Element | null {
    const logic = hogInvocationsLogic({ id, functionKind })
    const {
        runs,
        runsLoading,
        filters,
        selectedIds,
        selectedCount,
        expandedIds,
        rerunableSelectedIds,
        hasMore,
        hasLoadedOnce,
        selectableIds,
        selectAllState,
        personPropertiesById,
        sparkline,
        sparklineLoading,
        sparklineErrored,
    } = useValues(logic)
    const {
        loadMore,
        refresh,
        setFilters,
        toggleSelected,
        clearSelected,
        setSelectedIds,
        setExpanded,
        rerunInvocations,
        bulkRerun,
    } = useActions(logic)
    const [rerunModalOpen, setRerunModalOpen] = useState(false)

    useEffect(() => {
        refresh()
    }, [refresh])

    if (!id) {
        return null
    }

    const columns: LemonTableColumns<HogInvocationRow> = [
        {
            title: (
                <LemonCheckbox
                    checked={selectAllState === 'all' ? true : selectAllState === 'some' ? 'indeterminate' : false}
                    disabledReason={selectableIds.length === 0 ? 'Nothing selectable in this view' : undefined}
                    onChange={() => {
                        if (selectAllState === 'all' || selectAllState === 'some') {
                            clearSelected()
                        } else {
                            setSelectedIds(selectableIds)
                        }
                    }}
                />
            ),
            key: 'select',
            width: 0,
            render: (_, row) => (
                <LemonCheckbox
                    checked={Boolean(selectedIds[row.invocation_id])}
                    onChange={() => toggleSelected(row.invocation_id)}
                    disabledReason={
                        isRerunWrapperKind(row.function_kind)
                            ? "Can't re-run a re-run"
                            : row.status === 'running'
                              ? "Can't rerun a run that's still in flight"
                              : undefined
                    }
                />
            ),
        },
        {
            title: 'Status',
            key: 'status',
            dataIndex: 'status',
            width: 0,
            render: (_, row) => (
                <div className="flex items-center gap-1">
                    <LemonTag type={tagTypeForStatus(row.status)}>{row.status.toUpperCase()}</LemonTag>
                    {row.problem_log_level && row.status === 'succeeded' ? (
                        <Tooltip
                            title={
                                row.problem_log_level === 'error'
                                    ? 'This run finished but logged an error. Expand the row to view it.'
                                    : 'This run finished but logged a warning. Expand the row to view it.'
                            }
                        >
                            <IconWarning
                                className={
                                    row.problem_log_level === 'error'
                                        ? 'text-danger text-base'
                                        : 'text-warning text-base'
                                }
                            />
                        </Tooltip>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Attempts',
            key: 'attempts',
            dataIndex: 'attempts',
            width: 0,
            render: (_, row) => <span className="font-mono">{row.attempts}</span>,
        },
        {
            title: 'First scheduled',
            key: 'first_scheduled_at',
            dataIndex: 'first_scheduled_at',
            sorter: true,
            render: (_, row) => <TZLabel time={row.first_scheduled_at} />,
        },
        {
            title: 'Latest scheduled',
            key: 'scheduled_at',
            dataIndex: 'scheduled_at',
            sorter: true,
            render: (_, row) => <TZLabel time={row.scheduled_at} />,
        },
        {
            title: 'Duration',
            key: 'duration_ms',
            dataIndex: 'duration_ms',
            render: (_, row) => <span className="font-mono">{formatDurationMs(row.duration_ms)}</span>,
        },
        {
            title: 'Event',
            key: 'event_uuid',
            dataIndex: 'event_uuid',
            render: (_, row) => {
                if (isRerunWrapperKind(row.function_kind)) {
                    return <LemonTag type="primary">RERUN</LemonTag>
                }
                return row.event_uuid ? (
                    <Link
                        to={urls.event(row.event_uuid, row.first_scheduled_at)}
                        className="font-mono text-xs"
                        title={row.event_uuid}
                    >
                        {shortId(row.event_uuid)}
                    </Link>
                ) : (
                    <span className="text-muted-alt">—</span>
                )
            },
        },
        {
            title: 'Person',
            key: 'person',
            render: (_, row) => {
                if (!row.person_id && !row.distinct_id) {
                    return <span className="text-muted-alt">—</span>
                }
                // Force `/persons/<uuid>` via `href` — default `asLink` prefers
                // distinct_id, which 404s when it's been merged/anonymized.
                const hydrated = row.person_id ? personPropertiesById[row.person_id] : undefined
                return (
                    <PersonDisplay
                        person={{
                            id: row.person_id,
                            distinct_ids: row.distinct_id ? [row.distinct_id] : [],
                            properties: hydrated?.properties,
                        }}
                        href={row.person_id ? urls.personByUUID(row.person_id) : undefined}
                        displayName={hydrated ? undefined : shortPersonDisplay(row)}
                        withIcon="sm"
                        noPopover
                    />
                )
            },
        },
        {
            title: 'Error',
            key: 'error_kind',
            dataIndex: 'error_kind',
            render: (_, row) =>
                row.status === 'failed' ? (
                    <span className="text-xs" title={row.error_message}>
                        <code className="text-danger">{row.error_kind || 'error'}</code>
                        {row.error_message ? (
                            <div className="text-muted-alt truncate max-w-100">
                                {row.error_message.slice(0, 80)}
                                {row.error_message.length > 80 ? '…' : ''}
                            </div>
                        ) : null}
                    </span>
                ) : (
                    <span className="text-muted-alt">—</span>
                ),
        },
        {
            title: 'Invocation',
            key: 'invocation_id',
            dataIndex: 'invocation_id',
            width: 0,
            render: (_, row) => (
                <code className="text-xs">
                    <CopyToClipboardInline explicitValue={row.invocation_id} selectable>
                        {shortId(row.invocation_id)}
                    </CopyToClipboardInline>
                </code>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, row) => {
                if (isRerunWrapperKind(row.function_kind)) {
                    return null
                }
                return (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        disabledReason={
                            row.status === 'running' ? "Can't rerun a run that's still in flight" : undefined
                        }
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Rerun this invocation?',
                                content:
                                    "We'll queue a rerun job for this run from its stored payload. " +
                                    'Inputs are re-resolved from the current function config, so any secret ' +
                                    'rotations will be picked up.',
                                primaryButton: {
                                    children: 'Rerun',
                                    onClick: () => rerunInvocations([row.invocation_id]),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }}
                    >
                        Rerun
                    </LemonButton>
                )
            },
        },
    ]

    return (
        <div className="flex-1 deprecated-space-y-2 flex flex-col min-w-0">
            <InvocationsBetaBanner />
            <InvocationsSparkline
                data={sparkline}
                loading={sparklineLoading}
                errored={sparklineErrored}
                onDateRangeChange={(date_from, date_to) => setFilters({ date_from, date_to })}
            />
            <div className="flex flex-wrap items-center gap-2 justify-between">
                <div className="flex items-center gap-2 flex-1 min-w-100">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search by invocation, event, distinct, or person ID…"
                        fullWidth
                        value={filters.search ?? ''}
                        onChange={(value) => setFilters({ search: value || undefined })}
                        prefix={<IconSearch />}
                        allowClear
                    />
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <StatusFilterDropdown
                        value={filters.status ?? []}
                        onChange={(next) =>
                            setFilters({
                                status: next.length ? next : undefined,
                            })
                        }
                    />
                    <LemonSelect<'all' | 'invocations' | 'rerun_jobs'>
                        size="small"
                        value={filters.kind ?? 'all'}
                        onChange={(v) =>
                            setFilters({
                                kind: v === 'invocations' || v === 'rerun_jobs' ? v : undefined,
                            })
                        }
                        options={[
                            { value: 'all', label: 'All rows' },
                            { value: 'invocations', label: 'Invocations only' },
                            { value: 'rerun_jobs', label: 'Rerun jobs only' },
                        ]}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconWarning />}
                        active={!!filters.problem_only}
                        onClick={() => setFilters({ problem_only: filters.problem_only ? undefined : true })}
                        tooltip="Show only runs that logged an error or warning — e.g. an email bounce or complaint that arrived after the run finished"
                    >
                        Logged errors
                    </LemonButton>
                    <DateFilter
                        size="small"
                        dateTo={filters.date_to ?? undefined}
                        dateFrom={filters.date_from}
                        onChange={(from, to) =>
                            setFilters({
                                date_from: from || '-24h',
                                date_to: to || undefined,
                            })
                        }
                        dateOptions={INVOCATIONS_DATE_OPTIONS}
                        allowTimePrecision
                        allowFixedRangeWithTime
                        allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks', 'months']}
                        use24HourFormat
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={runsLoading || sparklineLoading}
                        onClick={() => refresh()}
                    >
                        Refresh
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconRevert />}
                        onClick={() => setRerunModalOpen(true)}
                    >
                        Re-run…
                    </LemonButton>
                </div>
            </div>

            <RerunModal
                isOpen={rerunModalOpen}
                onClose={() => setRerunModalOpen(false)}
                initialDateFrom={filters.date_from}
                initialDateTo={filters.date_to}
                countMatches={(params) => countRerunMatches({ id, functionKind }, params)}
                onSubmit={(params) => {
                    bulkRerun(params)
                    setRerunModalOpen(false)
                }}
            />

            {selectedCount > 0 ? (
                <div className="flex items-center justify-between border rounded p-2 bg-bg-light">
                    <div className="text-sm">
                        {selectedCount} selected
                        {selectedCount > HOG_INVOCATIONS_RERUN_MAX_COUNT ? (
                            <span className="text-danger ml-2">
                                Maximum is {HOG_INVOCATIONS_RERUN_MAX_COUNT} per request.
                            </span>
                        ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton size="small" type="tertiary" onClick={() => clearSelected()}>
                            Clear
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            disabledReason={
                                rerunableSelectedIds.length === 0
                                    ? 'Selected runs are all still in flight'
                                    : selectedCount > HOG_INVOCATIONS_RERUN_MAX_COUNT
                                      ? `Selected ${selectedCount} > limit ${HOG_INVOCATIONS_RERUN_MAX_COUNT}`
                                      : undefined
                            }
                            onClick={() => {
                                LemonDialog.open({
                                    title: `Rerun ${rerunableSelectedIds.length} invocations?`,
                                    content:
                                        "We'll queue a single rerun job that drains these in the background. " +
                                        'Inputs (secrets, integration tokens) are re-resolved per run at execution ' +
                                        'time using the current function config.',
                                    primaryButton: {
                                        children: `Rerun ${rerunableSelectedIds.length}`,
                                        onClick: () => rerunInvocations(rerunableSelectedIds),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Rerun selected
                        </LemonButton>
                    </div>
                </div>
            ) : null}

            <LemonTable
                dataSource={runs}
                columns={columns}
                loading={runsLoading && !hasLoadedOnce}
                rowKey={(row) => row.invocation_id}
                // `min-w-0` lets the table shrink to its flex parent so its own
                // ScrollableShadows handles horizontal overflow — without it the
                // wide column set pushes the whole page into a horizontal scroll.
                className="ph-no-capture overflow-y-auto min-w-0"
                // `hover:!` modifiers beat LemonTable's default
                // `hover:bg-accent-highlight-secondary` once `onClick` is set.
                rowRibbonColor={(row) => rowRibbonColorFor(row)}
                sorting={{
                    columnKey: filters.order_by === 'first_scheduled' ? 'first_scheduled_at' : 'scheduled_at',
                    order: -1,
                }}
                onSort={(next) =>
                    setFilters({
                        order_by: next?.columnKey === 'first_scheduled_at' ? 'first_scheduled' : 'latest_scheduled',
                    })
                }
                noSortingCancellation
                onRow={(record) => ({
                    onClick: (e) => {
                        const target = e.target as HTMLElement | null
                        if (
                            target &&
                            target.closest(
                                'a, button, input, label, .LemonCheckbox, [role="button"], [data-attr="expand-row"]'
                            )
                        ) {
                            return
                        }
                        setExpanded(record.invocation_id, !expandedIds[record.invocation_id])
                    },
                })}
                expandable={{
                    noIndent: true,
                    isRowExpanded: (record) => expandedIds[record.invocation_id] ?? false,
                    onRowExpand: (record) => setExpanded(record.invocation_id, true),
                    onRowCollapse: (record) => setExpanded(record.invocation_id, false),
                    expandedRowRender: (record) => (
                        <RunDetail
                            record={record}
                            functionKind={functionKind}
                            hogFunctionId={id}
                            renderLogMessage={renderLogMessage}
                        />
                    ),
                }}
                emptyState={
                    <div className="py-8 text-center text-muted-alt">
                        {runsLoading ? 'Loading invocations…' : 'No invocations match these filters.'}
                    </div>
                }
            />

            {runs.length > 0 && hasMore ? (
                <div className="flex justify-center py-2">
                    <LemonButton size="small" type="secondary" loading={runsLoading} onClick={() => loadMore(null)}>
                        Load more
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

function RunDetail({
    record,
    functionKind,
    hogFunctionId,
    renderLogMessage,
}: {
    record: HogInvocationRow
    functionKind: HogInvocationsLogicProps['functionKind']
    hogFunctionId: string
    renderLogMessage?: (message: string) => JSX.Element | string
}): JSX.Element {
    const isRerunWrapper = isRerunWrapperKind(record.function_kind)
    const logsLogicProps: LogsViewerLogicProps = {
        sourceType: functionKind,
        sourceId: hogFunctionId,
        logicKey: `invocations-${record.invocation_id}`,
        defaultFilters: { instanceId: record.invocation_id },
        groupByInstanceId: false,
    }

    return (
        <div className="p-3 deprecated-space-y-3 bg-surface-secondary min-w-0">
            <div className="border rounded bg-surface-primary p-3">
                <dl className="grid grid-cols-[minmax(7rem,max-content)_1fr] items-baseline gap-x-4 gap-y-2 text-xs m-0">
                    <DetailField label={isRerunWrapper ? 'Re-run job ID' : 'Invocation ID'} mono>
                        <CopyToClipboardInline explicitValue={record.invocation_id} selectable>
                            {record.invocation_id}
                        </CopyToClipboardInline>
                    </DetailField>
                    {record.started_at ? (
                        <DetailField label="Started">
                            <TZLabel time={record.started_at} />
                        </DetailField>
                    ) : null}
                    {record.finished_at ? (
                        <DetailField label="Finished">
                            <TZLabel time={record.finished_at} />
                        </DetailField>
                    ) : null}
                    {record.parent_run_id ? (
                        <DetailField label="Parent run" mono>
                            <CopyToClipboardInline explicitValue={record.parent_run_id} selectable>
                                {record.parent_run_id}
                            </CopyToClipboardInline>
                        </DetailField>
                    ) : null}
                    {isRerunWrapper ? null : record.distinct_id ? (
                        <DetailField label="Distinct ID" mono>
                            <CopyToClipboardInline explicitValue={record.distinct_id} selectable>
                                {record.distinct_id}
                            </CopyToClipboardInline>
                        </DetailField>
                    ) : null}
                    {isRerunWrapper ? null : record.person_id ? (
                        <DetailField label="Person ID" mono>
                            <CopyToClipboardInline explicitValue={record.person_id} selectable>
                                {record.person_id}
                            </CopyToClipboardInline>
                        </DetailField>
                    ) : null}
                </dl>
            </div>

            {record.status === 'failed' && record.error_message ? (
                <div className="border border-danger rounded p-2 bg-danger-highlight">
                    <div className="text-xs text-danger font-semibold mb-1">
                        {record.error_kind ? record.error_kind : 'error'}
                    </div>
                    <pre className="text-xs text-danger whitespace-pre-wrap break-all m-0">{record.error_message}</pre>
                </div>
            ) : null}

            <div className="border rounded bg-surface-primary p-3">
                <LogsViewer
                    {...logsLogicProps}
                    hideDateFilter
                    hideInstanceIdColumn
                    defaultAscending
                    renderMessage={renderLogMessage ?? ((message) => renderHogFunctionMessage(message))}
                />
            </div>
        </div>
    )
}

function DetailField({
    label,
    value,
    mono,
    children,
}: {
    label: string
    value?: string
    mono?: boolean
    children?: ReactNode
}): JSX.Element {
    return (
        <>
            <dt className="text-muted-alt font-medium">{label}</dt>
            <dd className={`m-0 min-w-0 ${mono ? 'font-mono break-all' : ''}`}>{children ?? value}</dd>
        </>
    )
}

function RerunModal({
    isOpen,
    onClose,
    initialDateFrom,
    initialDateTo,
    countMatches,
    onSubmit,
}: {
    isOpen: boolean
    onClose: () => void
    initialDateFrom: string
    initialDateTo: string | undefined
    countMatches: (params: BulkRerunParams) => Promise<number>
    onSubmit: (params: BulkRerunParams) => void
}): JSX.Element {
    const [status, setStatus] = useState<RunStatus[]>(['failed'])
    const [errorKinds, setErrorKinds] = useState<string[]>([])
    const [maxCount, setMaxCount] = useState<number | undefined>(undefined)
    const [maxAttempts, setMaxAttempts] = useState<number | undefined>(undefined)
    const [dateFrom, setDateFrom] = useState<string>(initialDateFrom)
    const [dateTo, setDateTo] = useState<string | undefined>(initialDateTo)
    const [previewCount, setPreviewCount] = useState<number | null>(null)
    const [previewLoading, setPreviewLoading] = useState(false)

    // Debounced live count of invocations matching the current filter so the
    // user knows how many runs they're about to re-queue before they click.
    // Skip the explicit max_count cap in the preview — that's a client-side
    // ceiling applied at the server, not a filter on matching rows.
    useEffect(() => {
        if (!isOpen || status.length === 0) {
            setPreviewCount(null)
            return
        }
        const params: BulkRerunParams = {
            date_from: dateFrom,
            date_to: dateTo,
            status,
            error_kind: errorKinds.length ? errorKinds : undefined,
            max_attempts: maxAttempts,
        }
        setPreviewLoading(true)
        const handle = setTimeout(() => {
            countMatches(params)
                .then((n) => setPreviewCount(n))
                .catch(() => setPreviewCount(null))
                .finally(() => setPreviewLoading(false))
        }, 400)
        return () => clearTimeout(handle)
    }, [isOpen, dateFrom, dateTo, status, errorKinds, maxAttempts, countMatches])

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Re-run invocations"
            description="Queue a re-run for every invocation that matches this filter within the window. Inputs (secrets, integration tokens) are re-resolved per row at execution time."
            width={520}
            footer={
                <div className="flex items-center justify-between w-full gap-2">
                    <div className="text-xs text-muted-alt">
                        {status.length === 0
                            ? 'Pick at least one status to preview matches'
                            : previewLoading && previewCount === null
                              ? 'Counting matching invocations…'
                              : previewCount !== null
                                ? typeof maxCount === 'number' && previewCount > maxCount
                                    ? `${previewCount.toLocaleString()} match — will re-run the first ${maxCount.toLocaleString()}`
                                    : `${previewCount.toLocaleString()} invocation${previewCount === 1 ? '' : 's'} match`
                                : ''}
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={
                                status.length === 0
                                    ? 'Pick at least one status'
                                    : previewCount === 0
                                      ? 'Nothing matches this filter'
                                      : undefined
                            }
                            onClick={() =>
                                onSubmit({
                                    date_from: dateFrom,
                                    date_to: dateTo,
                                    status,
                                    error_kind: errorKinds.length ? errorKinds : undefined,
                                    max_count: maxCount,
                                    max_attempts: maxAttempts,
                                })
                            }
                        >
                            Queue re-run
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="deprecated-space-y-3">
                <Row label="Window">
                    <DateFilter
                        size="small"
                        dateFrom={dateFrom}
                        dateTo={dateTo ?? undefined}
                        onChange={(from, to) => {
                            setDateFrom(from || '-24h')
                            setDateTo(to || undefined)
                        }}
                        dateOptions={INVOCATIONS_DATE_OPTIONS}
                        allowTimePrecision
                        allowFixedRangeWithTime
                        allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks', 'months']}
                        use24HourFormat
                    />
                </Row>
                <Row label="Status">
                    <LemonInputSelect
                        mode="multiple"
                        value={status}
                        // 'running' is omitted: in-flight invocations are skipped by the rerun worker's
                        // exactly-once guard, so offering it here would queue a rerun that re-fires nothing.
                        options={STATUS_OPTIONS.filter((o) => o.value !== 'running').map((o) => ({
                            key: o.value,
                            label: o.label,
                        }))}
                        onChange={(values) => setStatus(values as RunStatus[])}
                        placeholder="Pick statuses to re-run"
                    />
                </Row>
                <Row
                    label="Error kinds"
                    help="Free-text — only matters when filtering by failed. Match values from the Error column (e.g. http_5xx)."
                >
                    <LemonInputSelect
                        mode="multiple"
                        value={errorKinds}
                        options={[]}
                        allowCustomValues
                        onChange={(values) => setErrorKinds(values)}
                        placeholder="Leave empty for all"
                    />
                </Row>
                <Row label="Max invocations to re-run" help={`Server caps at ${HOG_INVOCATIONS_RERUN_MAX_COUNT}.`}>
                    <LemonInput
                        type="number"
                        min={1}
                        max={HOG_INVOCATIONS_RERUN_MAX_COUNT}
                        value={maxCount}
                        onChange={(v) => setMaxCount(typeof v === 'number' ? v : undefined)}
                        placeholder="Unlimited (up to server cap)"
                    />
                </Row>
                <Row
                    label="Skip rows with attempts ≥"
                    help="Useful to avoid re-running rows that have already retried a lot."
                >
                    <LemonInput
                        type="number"
                        min={1}
                        max={255}
                        value={maxAttempts}
                        onChange={(v) => setMaxAttempts(typeof v === 'number' ? v : undefined)}
                        placeholder="No cap"
                    />
                </Row>
            </div>
        </LemonModal>
    )
}

function StatusFilterDropdown({
    value,
    onChange,
}: {
    value: RunStatus[]
    onChange: (next: RunStatus[]) => void
}): JSX.Element {
    const label =
        value.length === 0 || value.length === STATUS_OPTIONS.length
            ? 'All statuses'
            : value.length === 1
              ? (STATUS_OPTIONS.find((o) => o.value === value[0])?.label ?? value[0])
              : `${value.length} statuses`
    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="deprecated-space-y-px p-1">
                    {STATUS_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.value}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={
                                <LemonCheckbox checked={value.includes(option.value)} className="pointer-events-none" />
                            }
                            onClick={() =>
                                onChange(
                                    value.includes(option.value)
                                        ? value.filter((v) => v !== option.value)
                                        : [...value, option.value]
                                )
                            }
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                {label}
            </LemonButton>
        </LemonDropdown>
    )
}

function Row({ label, help, children }: { label: string; help?: string; children: ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted-alt mb-1">{label}</div>
            {children}
            {help ? <div className="text-xs text-muted-alt mt-1">{help}</div> : null}
        </div>
    )
}
