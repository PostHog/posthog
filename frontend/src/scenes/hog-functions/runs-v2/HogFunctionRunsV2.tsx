import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagProps,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'

import { renderHogFunctionMessage } from '../logs/HogFunctionLogs'
import { LogsViewer } from '../logs/LogsViewer'
import { LogsViewerLogicProps } from '../logs/logsViewerLogic'
import {
    HogFunctionRunRow,
    HogFunctionRunsV2LogicProps,
    RUNS_V2_REPLAY_MAX_COUNT,
    RunStatus,
    hogFunctionRunsV2Logic,
} from './hogFunctionRunsV2Logic'

const STATUS_OPTIONS: { value: RunStatus; label: string }[] = [
    { value: 'running', label: 'Running' },
    { value: 'succeeded', label: 'Succeeded' },
    { value: 'failed', label: 'Failed' },
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

/**
 * "Runs" tab for a hog function or hog flow — the new view backed by
 * `hog_invocation_results`. Master/detail: each row collapses lifecycle
 * events for an invocation; expanding shows the existing `LogsViewer`
 * keyed on `instance_id = invocation_id`.
 *
 * Replay is async — clicking the action posts to `/replay`, which only
 * enqueues a cyclotron wrapper job. The toast surfaces the `replay_job_id`;
 * new lifecycle rows show up here once the worker drains the job.
 */
export function HogFunctionRunsV2({ id, functionKind }: HogFunctionRunsV2LogicProps): JSX.Element | null {
    const logic = hogFunctionRunsV2Logic({ id, functionKind })
    const { runs, runsLoading, filters, selectedIds, selectedCount, expandedIds, replayableSelectedIds } =
        useValues(logic)
    const { loadRuns, setFilters, resetFilters, toggleSelected, clearSelected, setExpanded, replayInvocations } =
        useActions(logic)

    useEffect(() => {
        loadRuns(null)
    }, [loadRuns])

    if (!id) {
        return null
    }

    const columns: LemonTableColumns<HogFunctionRunRow> = [
        {
            title: '',
            key: 'select',
            width: 0,
            render: (_, row) => (
                <LemonCheckbox
                    checked={Boolean(selectedIds[row.invocation_id])}
                    onChange={() => toggleSelected(row.invocation_id)}
                    disabledReason={row.status === 'running' ? "Can't replay a run that's still in flight" : undefined}
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
                    {row.is_retry ? (
                        <LemonTag type="muted" title="This run was a replay of an earlier invocation">
                            replay
                        </LemonTag>
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
            title: 'Scheduled',
            key: 'scheduled_at',
            dataIndex: 'scheduled_at',
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
            render: (_, row) =>
                row.event_uuid ? (
                    <code className="text-xs">
                        <CopyToClipboardInline explicitValue={row.event_uuid} selectable>
                            {shortId(row.event_uuid)}
                        </CopyToClipboardInline>
                    </code>
                ) : (
                    <span className="text-muted-alt">—</span>
                ),
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
            render: (_, row) => (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabledReason={row.status === 'running' ? "Can't replay a run that's still in flight" : undefined}
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Replay this invocation?',
                            content:
                                "We'll queue a replay job for this run from its stored payload. " +
                                'Inputs are re-resolved from the current function config, so any secret ' +
                                'rotations will be picked up.',
                            primaryButton: {
                                children: 'Replay',
                                onClick: () => replayInvocations([row.invocation_id]),
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Replay
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="flex-1 deprecated-space-y-2 flex flex-col">
            <div className="flex flex-wrap items-center gap-2 justify-between">
                <div className="flex items-center gap-2 flex-1 min-w-100">
                    <LemonInput
                        type="search"
                        placeholder="Search by invocation, event, distinct, or person ID…"
                        fullWidth
                        value={filters.search ?? ''}
                        onChange={(value) => setFilters({ search: value || undefined })}
                        prefix={<IconSearch />}
                        allowClear
                    />
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonSelect<RunStatus | 'all'>
                        size="small"
                        value={filters.status?.[0] ?? 'all'}
                        onChange={(v) =>
                            setFilters({
                                status: v === 'all' || !v ? undefined : [v as RunStatus],
                            })
                        }
                        options={[{ value: 'all', label: 'All statuses' }, ...STATUS_OPTIONS]}
                    />
                    <LemonSelect<'all' | 'only_originals' | 'only_retries'>
                        size="small"
                        value={filters.is_retry ?? 'all'}
                        onChange={(v) =>
                            setFilters({
                                is_retry:
                                    v === 'only_originals' || v === 'only_retries'
                                        ? (v as 'only_originals' | 'only_retries')
                                        : undefined,
                            })
                        }
                        options={[
                            { value: 'all', label: 'All runs' },
                            { value: 'only_originals', label: 'Originals only' },
                            { value: 'only_retries', label: 'Replays only' },
                        ]}
                    />
                    <DateFilter
                        dateTo={filters.date_to ?? undefined}
                        dateFrom={filters.date_from}
                        onChange={(from, to) =>
                            setFilters({
                                date_from: from || '-24h',
                                date_to: to || undefined,
                            })
                        }
                        allowedRollingDateOptions={['days', 'weeks', 'months']}
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={runsLoading}
                        onClick={() => loadRuns(null)}
                    >
                        Refresh
                    </LemonButton>
                    <LemonButton size="small" type="tertiary" onClick={() => resetFilters()}>
                        Reset
                    </LemonButton>
                </div>
            </div>

            {selectedCount > 0 ? (
                <div className="flex items-center justify-between border rounded p-2 bg-bg-light">
                    <div className="text-sm">
                        {selectedCount} selected
                        {selectedCount > RUNS_V2_REPLAY_MAX_COUNT ? (
                            <span className="text-danger ml-2">Maximum is {RUNS_V2_REPLAY_MAX_COUNT} per request.</span>
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
                                replayableSelectedIds.length === 0
                                    ? 'Selected runs are all still in flight'
                                    : selectedCount > RUNS_V2_REPLAY_MAX_COUNT
                                      ? `Selected ${selectedCount} > limit ${RUNS_V2_REPLAY_MAX_COUNT}`
                                      : undefined
                            }
                            onClick={() => {
                                LemonDialog.open({
                                    title: `Replay ${replayableSelectedIds.length} invocations?`,
                                    content:
                                        "We'll queue a single replay job that drains these in the background. " +
                                        'Inputs (secrets, integration tokens) are re-resolved per run at execution ' +
                                        'time using the current function config.',
                                    primaryButton: {
                                        children: `Replay ${replayableSelectedIds.length}`,
                                        onClick: () => replayInvocations(replayableSelectedIds),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Replay selected
                        </LemonButton>
                    </div>
                </div>
            ) : null}

            <LemonTable
                dataSource={runs}
                columns={columns}
                loading={runsLoading}
                rowKey={(row) => row.invocation_id}
                className="ph-no-capture overflow-y-auto"
                expandable={{
                    noIndent: true,
                    isRowExpanded: (record) => expandedIds[record.invocation_id] ?? false,
                    onRowExpand: (record) => setExpanded(record.invocation_id, true),
                    onRowCollapse: (record) => setExpanded(record.invocation_id, false),
                    expandedRowRender: (record) => (
                        <RunDetail record={record} functionKind={functionKind} hogFunctionId={id} />
                    ),
                }}
                emptyState={
                    <div className="py-8 text-center text-muted-alt">
                        {runsLoading ? 'Loading runs…' : 'No invocations match these filters.'}
                    </div>
                }
            />
        </div>
    )
}

/**
 * Detail panel rendered when a row is expanded. Pulls the logs for this
 * single invocation via the existing `LogsViewer` (no HogQL change needed —
 * `log_entries` uses `instance_id = invocation_id`).
 */
function RunDetail({
    record,
    functionKind,
    hogFunctionId,
}: {
    record: HogFunctionRunRow
    functionKind: HogFunctionRunsV2LogicProps['functionKind']
    hogFunctionId: string
}): JSX.Element {
    const logsLogicProps: LogsViewerLogicProps = {
        sourceType: functionKind,
        sourceId: hogFunctionId,
        // Pin the logs viewer to this one invocation — log_entries uses
        // instance_id = invocation_id.
        logicKey: `runsv2-${record.invocation_id}`,
        defaultFilters: { instanceId: record.invocation_id },
        groupByInstanceId: false,
    }

    return (
        <div className="p-4 deprecated-space-y-3 bg-bg-light">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                <Field label="Invocation ID" value={record.invocation_id} mono />
                <Field label="Status" value={record.status} />
                <Field label="Attempts" value={String(record.attempts)} mono />
                <Field label="Replay" value={record.is_retry ? 'Yes — this run was a replay' : 'No — original run'} />
                <Field label="Scheduled at" value={record.scheduled_at} mono />
                <Field label="Started at" value={record.started_at ?? '—'} mono />
                <Field label="Finished at" value={record.finished_at ?? '—'} mono />
                <Field label="Duration" value={formatDurationMs(record.duration_ms)} mono />
                {record.event_uuid ? <Field label="Trigger event" value={record.event_uuid} mono /> : null}
                {record.distinct_id ? <Field label="Distinct ID" value={record.distinct_id} mono /> : null}
                {record.person_id ? <Field label="Person ID" value={record.person_id} mono /> : null}
                {record.parent_run_id ? <Field label="Parent run" value={record.parent_run_id} mono /> : null}
            </div>

            {record.status === 'failed' && record.error_message ? (
                <div className="border rounded p-2 bg-bg-base">
                    <div className="text-xs text-muted-alt mb-1">
                        {record.error_kind ? `${record.error_kind} — error_message:` : 'error_message:'}
                    </div>
                    <pre className="text-xs whitespace-pre-wrap break-all m-0">{record.error_message}</pre>
                </div>
            ) : null}

            <div className="border rounded p-2 bg-bg-base">
                <div className="text-xs text-muted-alt mb-2">Logs for this invocation</div>
                <LogsViewer
                    {...logsLogicProps}
                    hideDateFilter
                    hideInstanceIdColumn
                    renderMessage={(message) => renderHogFunctionMessage(message)}
                />
            </div>
        </div>
    )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }): JSX.Element {
    return (
        <>
            <div className="text-muted-alt">{label}</div>
            <div className={mono ? 'font-mono text-xs break-all' : undefined}>{value}</div>
        </>
    )
}
