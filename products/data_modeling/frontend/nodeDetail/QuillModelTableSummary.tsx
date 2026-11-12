import type { ReactNode } from 'react'

import { Badge, Button, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SyncFrequencyLabelMap, SyncTypeLabelMap } from 'products/data_warehouse/frontend/utils'

import type { ModelTableSummaryProps } from './ModelTableSummary'
import { QuillModelDownstreamSummary } from './QuillModelDownstreamSummary'
import { QuillModelErrorText } from './QuillModelErrorText'
import { QuillModelFact } from './QuillModelFact'
import { QuillModelFacts } from './QuillModelFacts'
import { QuillModelSummaryCard } from './QuillModelSummaryCard'
import { schemaStatusBadgeVariant } from './quillNodeDetailBadges'

function Title({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Text size="xs" weight="semibold" render={<span />}>
            {children}
        </Text>
    )
}

export function QuillModelTableSummary({
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
}: ModelTableSummaryProps): JSX.Element {
    const downstream = (
        <QuillModelDownstreamSummary
            downstreamCount={node.downstream_count}
            lineageUrl={urls.nodeDetail(id, 'lineage')}
        />
    )

    if (node.origin === 'posthog') {
        return (
            <QuillModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
                <Title>Managed by PostHog</Title>
                <QuillModelFacts>
                    <QuillModelFact label="Source">PostHog</QuillModelFact>
                    {downstream}
                </QuillModelFacts>
            </QuillModelSummaryCard>
        )
    }

    if (loading) {
        return (
            <QuillModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
                <Skeleton className="h-20 w-full" />
            </QuillModelSummaryCard>
        )
    }

    if (error) {
        return (
            <QuillModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="xs" variant="muted" render={<span />}>
                        {accessDenied
                            ? "You don't have access to this table's details."
                            : "Couldn't load table details. Try again."}
                    </Text>
                    {!accessDenied && (
                        <Button variant="outline" size="sm" onClick={onRetry} loading={loading}>
                            Retry
                        </Button>
                    )}
                </div>
                <QuillModelFacts>{downstream}</QuillModelFacts>
            </QuillModelSummaryCard>
        )
    }

    const title = schema ? 'Current status' : source?.access_method === 'direct' ? 'Direct query table' : 'Table'
    const sourceUrl = source
        ? schema
            ? urls.dataWarehouseSourceSchema(`managed-${source.id}`, schema.id)
            : urls.dataWarehouseSource(`managed-${source.id}`)
        : null

    return (
        <QuillModelSummaryCard metadata={metadata} dataAttr="node-detail-table">
            <div className="flex flex-wrap items-center gap-2">
                <Title>{title}</Title>
                {schema &&
                    (schema.status ? (
                        <Badge variant={schemaStatusBadgeVariant(schema.status)}>{schema.status}</Badge>
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            —
                        </Text>
                    ))}
            </div>
            {schema?.latest_error && schema.status === 'Failed' && <QuillModelErrorText error={schema.latest_error} />}
            <QuillModelFacts>
                {source && sourceUrl ? (
                    <QuillModelFact label="Source">
                        <Button variant="link" size="inline" render={<LinkPrimitive to={sourceUrl} />}>
                            {source.source_type}
                        </Button>
                    </QuillModelFact>
                ) : table ? (
                    <QuillModelFact label="File format">
                        {table.format === 'CSVWithNames' ? 'CSV with headers' : table.format}
                    </QuillModelFact>
                ) : null}
                {schema && (
                    <>
                        <QuillModelFact label="Last synced">
                            {schema.last_synced_at ? <TZLabel time={schema.last_synced_at} /> : 'Never'}
                        </QuillModelFact>
                        <QuillModelFact label="Sync method">
                            {schema.sync_type ? SyncTypeLabelMap[schema.sync_type] : 'Not set up'}
                        </QuillModelFact>
                        <QuillModelFact label="Sync schedule">
                            {schema.sync_frequency ? SyncFrequencyLabelMap[schema.sync_frequency] : 'Not set up'}
                        </QuillModelFact>
                    </>
                )}
                {downstream}
            </QuillModelFacts>
        </QuillModelSummaryCard>
    )
}
