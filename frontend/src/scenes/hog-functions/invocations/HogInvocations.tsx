import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { IconRefresh, IconRevert, IconSearch } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagProps,
} from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { renderHogFunctionMessage } from '../logs/HogFunctionLogs'
import { LogsViewer } from '../logs/LogsViewer'
import { LogsViewerLogicProps } from '../logs/logsViewerLogic'
import {
    BulkReplayParams,
    HogInvocationRow,
    HogInvocationsLogicProps,
    HOG_INVOCATIONS_REPLAY_MAX_COUNT,
    RunStatus,
    hogInvocationsLogic,
    isReplayWrapperKind,
} from './hogInvocationsLogic'
import { InvocationsBetaBanner } from './InvocationsTabBanners'

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
export function HogInvocations({ id, functionKind }: HogInvocationsLogicProps): JSX.Element | null {
    const logic = hogInvocationsLogic({ id, functionKind })
    const {
        runs,
        runsLoading,
        filters,
        selectedIds,
        selectedCount,
        expandedIds,
        replayableSelectedIds,
        hasMore,
        hasLoadedOnce,
    } = useValues(logic)
    const {
        loadRuns,
        loadMore,
        setFilters,
        toggleSelected,
        clearSelected,
        setExpanded,
        replayInvocations,
        bulkReplay,
    } = useActions(logic)
    const [rerunModalOpen, setRerunModalOpen] = useState(false)

    useEffect(() => {
        loadRuns(null)
    }, [loadRuns])

    if (!id) {
        return null
    }

    const columns: LemonTableColumns<HogInvocationRow> = [
        {
            title: '',
            key: 'select',
            width: 0,
            render: (_, row) => (
                <LemonCheckbox
                    checked={Boolean(selectedIds[row.invocation_id])}
                    onChange={() => toggleSelected(row.invocation_id)}
                    disabledReason={
                        isReplayWrapperKind(row.function_kind)
                            ? "Can't re-run a re-run"
                            : row.status === 'running'
                              ? "Can't replay a run that's still in flight"
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
                    {isReplayWrapperKind(row.function_kind) ? (
                        <LemonTag
                            type="primary"
                            title="This row tracks a bulk re-run, not an individual invocation. Expand for logs."
                        >
                            re-run
                        </LemonTag>
                    ) : row.is_retry ? (
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
                    <Link
                        to={urls.event(row.event_uuid, row.scheduled_at)}
                        className="font-mono text-xs"
                        title={row.event_uuid}
                    >
                        {shortId(row.event_uuid)}
                    </Link>
                ) : (
                    <span className="text-muted-alt">—</span>
                ),
        },
        {
            title: 'Person',
            key: 'person',
            render: (_, row) =>
                row.person_id || row.distinct_id ? (
                    // Build the minimum-viable PersonPropType from what we
                    // store on the lifecycle row. `id` is optional in the
                    // type but, when set, lets PersonDisplay link to the
                    // person page even without properties hydrated.
                    <PersonDisplay
                        person={{
                            id: row.person_id,
                            distinct_ids: row.distinct_id ? [row.distinct_id] : [],
                        }}
                        displayName={row.distinct_id || row.person_id || undefined}
                        withIcon="sm"
                        noPopover
                    />
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
                    disabledReason={
                        isReplayWrapperKind(row.function_kind)
                            ? "Can't re-run a re-run"
                            : row.status === 'running'
                              ? "Can't replay a run that's still in flight"
                              : undefined
                    }
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
            <InvocationsBetaBanner />
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
                initialStatus={filters.status}
                onSubmit={(params) => {
                    bulkReplay(params)
                    setRerunModalOpen(false)
                }}
            />

            {selectedCount > 0 ? (
                <div className="flex items-center justify-between border rounded p-2 bg-bg-light">
                    <div className="text-sm">
                        {selectedCount} selected
                        {selectedCount > HOG_INVOCATIONS_REPLAY_MAX_COUNT ? (
                            <span className="text-danger ml-2">
                                Maximum is {HOG_INVOCATIONS_REPLAY_MAX_COUNT} per request.
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
                                replayableSelectedIds.length === 0
                                    ? 'Selected runs are all still in flight'
                                    : selectedCount > HOG_INVOCATIONS_REPLAY_MAX_COUNT
                                      ? `Selected ${selectedCount} > limit ${HOG_INVOCATIONS_REPLAY_MAX_COUNT}`
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
                // Only show the full-table loading spinner on the very first
                // load; refreshes keep the existing rows visible (the Refresh
                // button itself spins) so the list doesn't "flash away".
                loading={runsLoading && !hasLoadedOnce}
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

/**
 * Detail panel rendered when a row is expanded. Pulls the logs for this
 * invocation via the existing `LogsViewer` (`log_entries.instance_id = invocation_id`).
 *
 * Designed not to duplicate anything already visible on the collapsed row —
 * only the values that aren't shown above (full IDs, started/finished
 * timestamps, parent run, full error, re-run filter) land here.
 */
function RunDetail({
    record,
    functionKind,
    hogFunctionId,
}: {
    record: HogInvocationRow
    functionKind: HogInvocationsLogicProps['functionKind']
    hogFunctionId: string
}): JSX.Element {
    const isReplayWrapper = isReplayWrapperKind(record.function_kind)
    const logsLogicProps: LogsViewerLogicProps = {
        sourceType: functionKind,
        sourceId: hogFunctionId,
        // Pin the logs viewer to this one invocation — log_entries uses
        // instance_id = invocation_id.
        logicKey: `invocations-${record.invocation_id}`,
        defaultFilters: { instanceId: record.invocation_id },
        groupByInstanceId: false,
    }

    return (
        <div className="p-3 deprecated-space-y-2 bg-surface-secondary">
            <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
                <DetailField label={isReplayWrapper ? 'Re-run job ID' : 'Invocation ID'} mono>
                    <CopyToClipboardInline explicitValue={record.invocation_id} selectable>
                        {record.invocation_id}
                    </CopyToClipboardInline>
                </DetailField>
                {record.started_at ? <DetailField label="Started" mono value={record.started_at} /> : null}
                {record.finished_at ? <DetailField label="Finished" mono value={record.finished_at} /> : null}
                {record.parent_run_id ? <DetailField label="Parent run" mono value={record.parent_run_id} /> : null}
                {isReplayWrapper ? null : record.distinct_id ? (
                    <DetailField label="Distinct ID" mono value={record.distinct_id} />
                ) : null}
                {isReplayWrapper ? null : record.person_id ? (
                    <DetailField label="Person ID" mono value={record.person_id} />
                ) : null}
            </div>

            {record.status === 'failed' && record.error_message ? (
                <div className="border border-danger rounded p-2 bg-danger-highlight">
                    <div className="text-xs text-danger font-semibold mb-1">
                        {record.error_kind ? record.error_kind : 'error'}
                    </div>
                    <pre className="text-xs text-danger whitespace-pre-wrap break-all m-0">{record.error_message}</pre>
                </div>
            ) : null}

            <div className="border rounded bg-surface-primary">
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
            <div className="text-muted-alt">{label}</div>
            <div className={mono ? 'font-mono break-all' : undefined}>{children ?? value}</div>
        </>
    )
}

/**
 * Modal for the "Re-run…" action. Lets the user kick off a bulk replay by
 * specifying a window + filter (status, error kind, caps) rather than picking
 * rows individually. The body shape matches `BulkReplayParams` and is forwarded
 * to the `bulkReplay` action which resolves the date strings before posting.
 */
function RerunModal({
    isOpen,
    onClose,
    initialDateFrom,
    initialDateTo,
    initialStatus,
    onSubmit,
}: {
    isOpen: boolean
    onClose: () => void
    initialDateFrom: string
    initialDateTo: string | undefined
    initialStatus: RunStatus[] | undefined
    onSubmit: (params: BulkReplayParams) => void
}): JSX.Element {
    // Default to "failed" — the most common re-run motion.
    const [status, setStatus] = useState<RunStatus[]>(initialStatus?.length ? initialStatus : ['failed'])
    const [errorKinds, setErrorKinds] = useState<string[]>([])
    const [maxCount, setMaxCount] = useState<number | undefined>(undefined)
    const [maxAttempts, setMaxAttempts] = useState<number | undefined>(undefined)
    const [dateFrom, setDateFrom] = useState<string>(initialDateFrom)
    const [dateTo, setDateTo] = useState<string | undefined>(initialDateTo)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Re-run invocations"
            description="Queue a re-run for every invocation that matches this filter within the window. Inputs (secrets, integration tokens) are re-resolved per row at execution time."
            width={520}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={status.length === 0 ? 'Pick at least one status' : undefined}
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
                </>
            }
        >
            <div className="deprecated-space-y-3">
                <Row label="Window">
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo ?? undefined}
                        onChange={(from, to) => {
                            setDateFrom(from || '-24h')
                            setDateTo(to || undefined)
                        }}
                        allowedRollingDateOptions={['days', 'weeks', 'months']}
                    />
                </Row>
                <Row label="Status">
                    <LemonInputSelect
                        mode="multiple"
                        value={status}
                        options={STATUS_OPTIONS.map((o) => ({ key: o.value, label: o.label }))}
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
                <Row label="Max invocations to re-run" help={`Server caps at ${HOG_INVOCATIONS_REPLAY_MAX_COUNT}.`}>
                    <LemonInput
                        type="number"
                        min={1}
                        max={HOG_INVOCATIONS_REPLAY_MAX_COUNT}
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

function Row({ label, help, children }: { label: string; help?: string; children: ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted-alt mb-1">{label}</div>
            {children}
            {help ? <div className="text-xs text-muted-alt mt-1">{help}</div> : null}
        </div>
    )
}
