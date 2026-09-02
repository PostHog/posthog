import type { ReactNode } from 'react'

import { IconDatabase } from '@posthog/icons'

import { getPermissionRequestToolInput, registerToolRenderers } from 'products/posthog_ai/frontend/api/tools'

import { certificationsLogic } from './certificationsLogic'
import type {
    DataCatalogCertificationApi,
    DataCatalogMetricApi,
    DataCatalogRelationshipProposalApi,
} from './generated/api.schemas'
import { metricsLogic } from './metricsLogic'
import { relationshipsLogic } from './relationshipsLogic'

interface PreviewField {
    label: string
    value: ReactNode
}

/**
 * The evidence block of a data catalog approval card: what the promotion touches, and the lifecycle
 * step it takes. The card's headline sentence carries only the certification, metric, or proposal id,
 * so this block is where the approver reads which catalog entity is affected.
 */
function CatalogPreviewCard({
    title,
    subtitle,
    fields,
}: {
    title: ReactNode
    subtitle?: ReactNode
    fields: PreviewField[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 min-w-0 text-xs">
            <div className="text-sm font-medium break-all">{title}</div>
            {subtitle && <div className="text-secondary">{subtitle}</div>}
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 min-w-0">
                {fields.map((field) => (
                    <div key={field.label} className="contents">
                        <span className="text-secondary whitespace-nowrap">{field.label}</span>
                        <span className="min-w-0 break-words">{field.value}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

/** A catalog identifier — a table, view, metric, or join key — set apart from prose. */
function Identifier({ children }: { children: string }): JSX.Element {
    return <span className="font-mono">{children}</span>
}

function statusChange(from: string, to: string): string {
    return `${from} → ${to}`
}

function stringArg(input: Record<string, unknown>, key: string): string | null {
    const value = input[key]
    return typeof value === 'string' && value ? value : null
}

/**
 * Preview for `data-catalog-certification-certify` / `-deprecate`, both addressed by certification id.
 * Returns null when the id is missing or names a certification the open scene has not loaded, so the
 * card falls back to the raw payload instead of previewing the wrong source.
 */
export function certificationPreview(
    input: Record<string, unknown>,
    certifications: DataCatalogCertificationApi[],
    decision: 'certified' | 'deprecated'
): ReactNode | null {
    const id = stringArg(input, 'id')
    const certification = id ? certifications.find((candidate) => candidate.id === id) : null
    if (!certification) {
        return null
    }
    const fields: PreviewField[] = [{ label: 'Change', value: statusChange(certification.status, decision) }]
    if (certification.notes) {
        fields.push({ label: 'Notes', value: certification.notes })
    }
    return (
        <CatalogPreviewCard
            title={<Identifier>{certification.target_name}</Identifier>}
            subtitle={certification.target_type === 'view' ? 'Warehouse view' : 'Warehouse table'}
            fields={fields}
        />
    )
}

/** Preview for `data-catalog-metric-approve`, addressed by metric name. */
export function metricApprovePreview(
    input: Record<string, unknown>,
    metrics: DataCatalogMetricApi[]
): ReactNode | null {
    const name = stringArg(input, 'name')
    const metric = name ? metrics.find((candidate) => candidate.name === name) : null
    if (!metric) {
        return null
    }
    const fields: PreviewField[] = [
        { label: 'Change', value: statusChange(metric.status, 'approved') },
        { label: 'Definition', value: metric.definition_kind ?? 'No query' },
    ]
    if (metric.unit) {
        fields.push({ label: 'Unit', value: metric.unit })
    }
    if (metric.description) {
        fields.push({ label: 'Meaning', value: metric.description })
    }
    if (metric.is_drifted) {
        fields.push({
            label: 'Drift',
            value: 'The definition no longer matches its source insight. Refresh or unlink it before you approve.',
        })
    }
    return (
        <CatalogPreviewCard
            title={metric.display_name || <Identifier>{metric.name}</Identifier>}
            subtitle={metric.display_name ? <Identifier>{metric.name}</Identifier> : undefined}
            fields={fields}
        />
    )
}

/** Preview for `data-catalog-relationship-accept` / `-reject`, both addressed by proposal id. */
export function relationshipPreview(
    input: Record<string, unknown>,
    proposals: DataCatalogRelationshipProposalApi[],
    decision: 'accepted' | 'rejected'
): ReactNode | null {
    const id = stringArg(input, 'id')
    const proposal = id ? proposals.find((candidate) => candidate.id === id) : null
    if (!proposal) {
        return null
    }
    const fields: PreviewField[] = [
        { label: 'Change', value: statusChange(proposal.status, decision) },
        {
            label: 'Accessor',
            value: <Identifier>{`${proposal.source_table_name}.${proposal.field_name}`}</Identifier>,
        },
    ]
    if (proposal.confidence != null) {
        fields.push({ label: 'Confidence', value: `${Math.round(proposal.confidence * 100)}%` })
    }
    if (proposal.reasoning) {
        fields.push({ label: 'Proposal reason', value: proposal.reasoning })
    }
    // A reject call persists this note permanently, so the approver has to read it before confirming.
    // It is distinct from `proposal.reasoning` (why the join was proposed), hence the separate label.
    const rejectionReason = decision === 'rejected' ? stringArg(input, 'rejection_reason') : null
    if (rejectionReason) {
        fields.push({ label: 'Rejection reason', value: rejectionReason })
    }
    return (
        <CatalogPreviewCard
            title={
                <Identifier>{`${proposal.source_table_name}.${proposal.source_table_key} → ${proposal.joining_table_name}.${proposal.joining_table_key}`}</Identifier>
            }
            fields={fields}
        />
    )
}

function certifications(): DataCatalogCertificationApi[] {
    return certificationsLogic.findMounted()?.values.certifications ?? []
}

function proposals(): DataCatalogRelationshipProposalApi[] {
    return relationshipsLogic.findMounted()?.values.proposals ?? []
}

// Register on module load (idempotent — re-registering the same key overwrites). Preview-only entries:
// no `Renderer`, so each tool-result card still resolves to the generic MCP card via `lookupToolRenderer`.
// `requiresPostHogOrigin`: an imported MCP server's tool with a colliding bare name must not have its
// approval payload dressed up as a first-party catalog card — untrusted calls keep the raw JSON payload.
registerToolRenderers([
    {
        key: 'data-catalog-certification-certify',
        displayName: 'Certify source',
        icon: <IconDatabase />,
        renderPermissionPreview: (record) =>
            certificationPreview(getPermissionRequestToolInput(record), certifications(), 'certified'),
        requiresPostHogOrigin: true,
    },
    {
        key: 'data-catalog-certification-deprecate',
        displayName: 'Deprecate source',
        icon: <IconDatabase />,
        renderPermissionPreview: (record) =>
            certificationPreview(getPermissionRequestToolInput(record), certifications(), 'deprecated'),
        requiresPostHogOrigin: true,
    },
    {
        key: 'data-catalog-metric-approve',
        displayName: 'Approve metric',
        icon: <IconDatabase />,
        renderPermissionPreview: (record) =>
            metricApprovePreview(
                getPermissionRequestToolInput(record),
                metricsLogic.findMounted()?.values.allMetrics ?? []
            ),
        requiresPostHogOrigin: true,
    },
    {
        key: 'data-catalog-relationship-accept',
        displayName: 'Accept relationship',
        icon: <IconDatabase />,
        renderPermissionPreview: (record) =>
            relationshipPreview(getPermissionRequestToolInput(record), proposals(), 'accepted'),
        requiresPostHogOrigin: true,
    },
    {
        key: 'data-catalog-relationship-reject',
        displayName: 'Reject relationship',
        icon: <IconDatabase />,
        renderPermissionPreview: (record) =>
            relationshipPreview(getPermissionRequestToolInput(record), proposals(), 'rejected'),
        requiresPostHogOrigin: true,
    },
])
