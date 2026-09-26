import type { ReactNode } from 'react'

import { IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { KnowledgeSource } from '../scenes/businessKnowledgeLogic'
import { StatusTag } from './StatusTag'

const SOURCE_TYPE_LABELS: Record<KnowledgeSource['source_type'], string> = {
    text: 'Text',
    url: 'URL',
    file: 'File',
}

function inAppPath(url: string): string {
    // Lemon Link treats https as external, so strip the origin. Keep /project/:id
    // because the ticket may live on a child environment, not this project.
    try {
        const parsed = new URL(url)
        return `${parsed.pathname}${parsed.search}`
    } catch {
        return url
    }
}

function formatFileSize(bytes: number): string {
    if (bytes < 1024) {
        return `${bytes} B`
    }
    if (bytes < 1024 * 1024) {
        return `${Math.round(bytes / 1024)} KB`
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function DetailRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex items-start justify-between gap-2">
            <span className="shrink-0 text-muted-alt">{label}</span>
            <span className="min-w-0 text-right">{children}</span>
        </div>
    )
}

export interface KnowledgeSourceDetailsProps {
    source: KnowledgeSource
    isRefreshing: boolean
    isDeleting: boolean
    onRefresh: () => void
    onDelete: () => void
}

export function KnowledgeSourceDetails({
    source,
    isRefreshing,
    isDeleting,
    onRefresh,
    onDelete,
}: KnowledgeSourceDetailsProps): JSX.Element {
    const canRefresh = source.source_type === 'url' && !source.is_generated

    return (
        <LemonCard hoverEffect={false} className="p-3">
            <h3 className="mb-2 text-sm font-semibold">Source</h3>
            <div className="space-y-2 text-xs">
                <DetailRow label="Status">
                    <StatusTag source={source} />
                </DetailRow>
                <DetailRow label="Type">
                    <LemonTag>{SOURCE_TYPE_LABELS[source.source_type]}</LemonTag>
                </DetailRow>
                {source.is_generated ? (
                    <DetailRow label="Origin">
                        <LemonTag
                            type="highlight"
                            title="PostHog added this from a resolved support ticket. You can edit or delete it."
                        >
                            Learned
                        </LemonTag>
                    </DetailRow>
                ) : null}
                {source.is_generated && source.learned_from_ticket_number != null ? (
                    <DetailRow label="Ticket">
                        {source.learned_from_ticket_url ? (
                            <Link
                                to={inAppPath(source.learned_from_ticket_url)}
                                // pinned: autocapture / Playwright key. Do not rename.
                                data-attr="business-knowledge-learned-ticket"
                                target="_blank"
                            >
                                #{source.learned_from_ticket_number}
                            </Link>
                        ) : (
                            <span>#{source.learned_from_ticket_number}</span>
                        )}
                    </DetailRow>
                ) : null}
                <DetailRow label="Created">
                    <TZLabel time={source.created_at} />
                </DetailRow>
                {source.updated_at ? (
                    <DetailRow label="Updated">
                        <TZLabel time={source.updated_at} />
                    </DetailRow>
                ) : null}
                <DetailRow label="Chunks">
                    <span translate="no">{source.chunk_count.toLocaleString()}</span>
                </DetailRow>
                {source.source_type === 'url' ? (
                    <DetailRow label="Pages">
                        <span translate="no">{source.document_count.toLocaleString()}</span>
                    </DetailRow>
                ) : null}
                {source.source_type === 'url' ? (
                    <DetailRow label="Last refresh">
                        {source.last_refresh_at ? (
                            <span className="inline-flex flex-col items-end gap-0.5">
                                <TZLabel time={source.last_refresh_at} />
                                {source.last_refresh_status === 'error' ? (
                                    <LemonTag type="danger" title={source.last_refresh_error || undefined}>
                                        refresh failed
                                    </LemonTag>
                                ) : null}
                            </span>
                        ) : (
                            <span className="text-muted">Never</span>
                        )}
                    </DetailRow>
                ) : null}
                {source.next_refresh_at ? (
                    <DetailRow label="Next refresh">
                        <TZLabel time={source.next_refresh_at} />
                    </DetailRow>
                ) : null}
                {source.source_type === 'file' && source.original_filename ? (
                    <DetailRow label="File">
                        <span className="block truncate" title={source.original_filename}>
                            {source.original_filename}
                        </span>
                    </DetailRow>
                ) : null}
                {source.file_size_bytes != null ? (
                    <DetailRow label="Size">
                        <span translate="no">{formatFileSize(source.file_size_bytes)}</span>
                    </DetailRow>
                ) : null}
            </div>
            <div className="mt-3 flex flex-wrap justify-end gap-2 border-t pt-3">
                {canRefresh ? (
                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        loading={isRefreshing}
                        disabledReason={isDeleting ? 'Deleting this source' : undefined}
                        onClick={onRefresh}
                        // pinned: autocapture / Playwright key. Do not rename.
                        data-attr="business-knowledge-source-refresh"
                    >
                        Refresh
                    </LemonButton>
                ) : null}
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    status="danger"
                    loading={isDeleting}
                    onClick={() => {
                        LemonDialog.open({
                            title: `Delete "${source.name}"?`,
                            description: 'Chunks will be removed.',
                            primaryButton: {
                                children: 'Delete',
                                status: 'danger',
                                onClick: onDelete,
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                    // pinned: autocapture / Playwright key. Do not rename.
                    data-attr="business-knowledge-source-delete"
                >
                    Delete
                </LemonButton>
            </div>
        </LemonCard>
    )
}
