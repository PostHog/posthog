import type { ReactNode } from 'react'

import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { DataModelingNode, DataWarehouseTable, ExternalDataSchemaWithSource, ExternalDataSource } from '~/types'

import { StatusTagSetting, SyncFrequencyLabelMap, SyncTypeLabelMap } from 'products/data_warehouse/frontend/utils'

import { ModelDownstreamSummary } from './ModelDownstreamSummary'
import { ModelSummaryCard } from './ModelSummaryCard'

export function ModelTableSummary({
    id,
    node,
    table,
    source,
    schema,
    loading,
    error,
    accessDenied,
    onRetry,
    metadata,
}: {
    id: string
    node: Pick<DataModelingNode, 'origin' | 'downstream_count'>
    table: DataWarehouseTable | null
    source: ExternalDataSource | null
    schema: ExternalDataSchemaWithSource | null
    loading: boolean
    error: boolean
    accessDenied: boolean
    onRetry: () => void
    metadata?: ReactNode
}): JSX.Element {
    const downstream = (
        <ModelDownstreamSummary
            downstreamCount={node.downstream_count}
            lineageUrl={urls.nodeDetail(id, 'lineage')}
        />
    )

    if (node.origin === 'posthog') {
        return (
            <ModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
                <div className="flex flex-col gap-3">
                    <span className="font-semibold">Managed by PostHog</span>
                    <dl className="flex flex-wrap gap-x-10 gap-y-3 mb-0 text-sm">
                        <div>
                            <dt className="text-secondary mb-1">Source</dt>
                            <dd className="mb-0">PostHog</dd>
                        </div>
                        {downstream}
                    </dl>
                </div>
            </ModelSummaryCard>
        )
    }

    if (loading) {
        return (
            <ModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
                <LemonSkeleton className="h-20 w-full" />
            </ModelSummaryCard>
        )
    }

    if (error) {
        return (
            <ModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
                <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-secondary">
                        <span>
                            {accessDenied
                                ? "You don't have access to this table's details."
                                : "Couldn't load table details. Try again."}
                        </span>
                        {!accessDenied && (
                            <LemonButton size="xsmall" onClick={onRetry} loading={loading}>
                                Retry
                            </LemonButton>
                        )}
                    </div>
                    <dl className="flex flex-wrap gap-x-10 gap-y-3 mb-0 text-sm">{downstream}</dl>
                </div>
            </ModelSummaryCard>
        )
    }

    const title = schema ? 'Current status' : source?.access_method === 'direct' ? 'Direct query table' : 'Table'
    const sourceUrl = source
        ? schema
            ? urls.dataWarehouseSourceSchema(`managed-${source.id}`, schema.id)
            : urls.dataWarehouseSource(`managed-${source.id}`)
        : null

    return (
        <ModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{title}</span>
                    {schema &&
                        (schema.status ? (
                            <LemonTag type={StatusTagSetting[schema.status] || 'default'}>{schema.status}</LemonTag>
                        ) : (
                            <span className="text-secondary">—</span>
                        ))}
                </div>
                {schema?.latest_error && schema.status === 'Failed' && (
                    <p className="mb-0 max-h-64 overflow-auto text-sm font-mono text-danger break-words whitespace-pre-wrap">
                        {schema.latest_error}
                    </p>
                )}
                <dl className="flex flex-wrap gap-x-10 gap-y-3 mb-0 text-sm">
                    {source && sourceUrl ? (
                        <div>
                            <dt className="text-secondary mb-1">Source</dt>
                            <dd className="mb-0">
                                <Link to={sourceUrl}>{source.source_type}</Link>
                            </dd>
                        </div>
                    ) : table ? (
                        <div>
                            <dt className="text-secondary mb-1">File format</dt>
                            <dd className="mb-0">{table.format === 'CSVWithNames' ? 'CSV with headers' : table.format}</dd>
                        </div>
                    ) : null}
                    {schema && (
                        <>
                            <div>
                                <dt className="text-secondary mb-1">Last synced</dt>
                                <dd className="mb-0">
                                    {schema.last_synced_at ? <TZLabel time={schema.last_synced_at} /> : 'Never'}
                                </dd>
                            </div>
                            <div>
                                <dt className="text-secondary mb-1">Sync method</dt>
                                <dd className="mb-0">
                                    {schema.sync_type ? SyncTypeLabelMap[schema.sync_type] : 'Not set up'}
                                </dd>
                            </div>
                            <div>
                                <dt className="text-secondary mb-1">Sync schedule</dt>
                                <dd className="mb-0">
                                    {schema.sync_frequency
                                        ? SyncFrequencyLabelMap[schema.sync_frequency]
                                        : 'Not set up'}
                                </dd>
                            </div>
                        </>
                    )}
                    {downstream}
                </dl>
            </div>
        </ModelSummaryCard>
    )
}
