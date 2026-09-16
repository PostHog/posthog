import { useActions, useValues } from 'kea'

import { IconRefresh, IconTrash } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import type { PrecomputeDebugBucketApi, PrecomputeDebugGroupApi } from './generated/api.schemas'
import { precomputeDebugLogic } from './precomputeDebugLogic'

export const scene: SceneExport = {
    component: PrecomputeDebugScene,
    logic: precomputeDebugLogic,
}

const STATUS_TAG_TYPE: Record<string, LemonTagType> = {
    ready: 'success',
    pending: 'warning',
    stale: 'caution',
    failed: 'danger',
}

function formatTtl(seconds: number | null): JSX.Element {
    if (seconds === null || seconds === undefined) {
        return <span className="text-muted">no TTL</span>
    }
    if (seconds < 0) {
        return <LemonTag type="danger">expired {humanFriendlyDuration(-seconds)} ago</LemonTag>
    }
    return <span>{humanFriendlyDuration(seconds)}</span>
}

function prettyQueryJson(queryJson: string | null): string | null {
    if (!queryJson) {
        return null
    }
    try {
        return JSON.stringify(JSON.parse(queryJson), null, 2)
    } catch {
        return queryJson
    }
}

function BucketsTable({ group }: { group: PrecomputeDebugGroupApi }): JSX.Element {
    const columns: LemonTableColumns<PrecomputeDebugBucketApi> = [
        {
            title: 'Bucket',
            render: (_, bucket) =>
                `${dayjs(bucket.time_range_start).format('YYYY-MM-DD HH:mm')} → ${dayjs(bucket.time_range_end).format(
                    'YYYY-MM-DD HH:mm'
                )}`,
        },
        {
            title: 'Status',
            render: (_, bucket) => (
                <LemonTag type={STATUS_TAG_TYPE[bucket.status] ?? 'default'}>{bucket.status}</LemonTag>
            ),
        },
        {
            title: 'Computed',
            render: (_, bucket) => (bucket.computed_at ? <TZLabel time={bucket.computed_at} /> : '—'),
        },
        {
            title: 'TTL remaining',
            render: (_, bucket) => formatTtl(bucket.ttl_seconds_remaining),
        },
    ]
    const sampleJson = prettyQueryJson(group.sample?.query_json ?? null)
    return (
        <div className="deprecated-space-y-2 py-2">
            {sampleJson ? (
                <div>
                    <div className="font-semibold mb-1">Originating query (from the latest insert)</div>
                    <CodeSnippet language={Language.JSON} maxLinesWithoutExpansion={12}>
                        {sampleJson}
                    </CodeSnippet>
                </div>
            ) : (
                <LemonBanner type="info">
                    No recent insert found in query_log for this hash, so the originating query can't be shown. It was
                    last built before the query_log lookback window.
                </LemonBanner>
            )}
            <LemonTable dataSource={group.buckets} columns={columns} size="small" embedded />
        </div>
    )
}

export function PrecomputeDebugScene(): JSX.Element {
    const { debugState, debugStateLoading, invalidatingHash } = useValues(precomputeDebugLogic)
    const { loadDebugState, invalidate } = useActions(precomputeDebugLogic)
    const { user } = useValues(userLogic)

    const confirmInvalidate = (queryHash: string | null): void => {
        LemonDialog.open({
            title: queryHash ? 'Mark this hash stale?' : 'Mark all precompute stale?',
            description: queryHash
                ? 'Ready jobs for this hash will be marked stale and recomputed on the next read.'
                : 'Every ready precompute job for this project will be marked stale and recomputed on the next read. Use this after a source resync changed the underlying data.',
            primaryButton: {
                children: 'Mark stale',
                status: 'danger',
                onClick: () => invalidate(queryHash),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const columns: LemonTableColumns<PrecomputeDebugGroupApi> = [
        {
            title: 'Query hash',
            render: (_, group) => <code className="text-xs">{group.query_hash.slice(0, 16)}…</code>,
        },
        {
            title: 'Serves',
            render: (_, group) =>
                group.sample?.query_type ? (
                    <LemonTag type="highlight">{group.sample.query_type}</LemonTag>
                ) : (
                    <span className="text-muted">unknown</span>
                ),
        },
        {
            title: 'Built by',
            render: (_, group) =>
                group.sample ? (
                    group.sample.trigger ? (
                        <LemonTag type="completion">warmer: {group.sample.trigger}</LemonTag>
                    ) : (
                        <LemonTag type="default">user read</LemonTag>
                    )
                ) : (
                    '—'
                ),
        },
        {
            title: 'Buckets',
            render: (_, group) => (
                <span>
                    {group.job_count}{' '}
                    <span className="text-muted">
                        (
                        {Object.entries(group.status_counts)
                            .map(([status, count]) => `${count} ${status}`)
                            .join(', ')}
                        )
                    </span>
                </span>
            ),
        },
        {
            title: 'Coverage',
            render: (_, group) =>
                `${dayjs(group.earliest_start).format('YYYY-MM-DD')} → ${dayjs(group.latest_end).format('YYYY-MM-DD')}`,
        },
        {
            title: 'Last computed',
            render: (_, group) => (group.last_computed_at ? <TZLabel time={group.last_computed_at} /> : '—'),
        },
        {
            width: 0,
            render: (_, group) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    loading={invalidatingHash === group.query_hash}
                    disabledReason={
                        invalidatingHash && invalidatingHash !== group.query_hash
                            ? 'Another invalidation is in progress'
                            : undefined
                    }
                    onClick={() => confirmInvalidate(group.query_hash)}
                >
                    Mark stale
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            {!user?.is_staff && (
                <LemonBanner type="warning">
                    This is a staff-only debug tool. The request will be rejected unless you are logged in as staff or
                    running in development.
                </LemonBanner>
            )}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-xl font-semibold mb-0">Precompute debug</h1>
                    <p className="text-muted mb-0">
                        Stored precompute hashes for this project: the buckets each covers, per-bucket TTL, and the
                        originating query each hash serves.
                        {debugState ? ` Showing ${debugState.groups.length} of ${debugState.total_hashes} hashes.` : ''}
                    </p>
                </div>
                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        loading={invalidatingHash === 'all'}
                        disabledReason={
                            invalidatingHash && invalidatingHash !== 'all'
                                ? 'Another invalidation is in progress'
                                : !debugState?.groups.length
                                  ? 'No precompute jobs to invalidate'
                                  : undefined
                        }
                        onClick={() => confirmInvalidate(null)}
                    >
                        Mark all stale
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={loadDebugState}
                        loading={debugStateLoading}
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>
            <LemonTable
                dataSource={debugState?.groups ?? []}
                columns={columns}
                loading={debugStateLoading}
                rowKey="query_hash"
                expandable={{
                    expandedRowRender: (group) => <BucketsTable group={group} />,
                }}
                emptyState="No precompute jobs stored for this project in the lookback window."
            />
        </div>
    )
}
