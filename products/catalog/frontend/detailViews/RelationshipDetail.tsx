import { LemonTag } from '@posthog/lemon-ui'

import type { CatalogNodeDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import { NODE_KIND_LABELS, RelationshipProposal, RELATIONSHIP_KIND_LABELS } from '../proposalTypes'

/**
 * Detail view for a CatalogRelationship proposal.
 * Renders source → target topology, the agent's reasoning, and confidence.
 */
export function RelationshipDetail({ proposal }: { proposal: RelationshipProposal }): JSX.Element {
    const { relationship, sourceNode, targetNode } = proposal
    const kindLabel = RELATIONSHIP_KIND_LABELS[relationship.kind] ?? relationship.kind

    return (
        <div className="flex flex-col gap-4">
            <section className="border rounded p-4 bg-surface-primary">
                <div className="flex items-center justify-center gap-4">
                    <NodeChip
                        node={sourceNode}
                        fallbackId={relationship.source_node_id}
                        columnName={relationship.source_column}
                    />
                    <div className="flex flex-col items-center">
                        <span className="text-xs text-muted-alt">{kindLabel}</span>
                        <span className="font-mono text-sm">↔</span>
                    </div>
                    <NodeChip
                        node={targetNode}
                        fallbackId={relationship.target_node_id}
                        columnName={relationship.target_column}
                    />
                </div>
            </section>

            {relationship.reasoning ? (
                <section>
                    <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-1">Reasoning</h4>
                    <p className="text-sm">{relationship.reasoning}</p>
                </section>
            ) : null}

            <section className="grid grid-cols-2 gap-4 text-xs text-muted-alt">
                <div>
                    <div className="uppercase tracking-wide mb-0.5">Discovered</div>
                    <div className="text-default">{relationship.discovered_at}</div>
                </div>
                <div>
                    <div className="uppercase tracking-wide mb-0.5">Last seen</div>
                    <div className="text-default">{relationship.last_seen_at}</div>
                </div>
            </section>
        </div>
    )
}

function NodeChip({
    node,
    fallbackId,
    columnName,
}: {
    node: CatalogNodeDTOApi | null
    fallbackId: string
    columnName: string | null
}): JSX.Element {
    return (
        <div className="border rounded p-3 min-w-32 text-center">
            <LemonTag type="primary" size="small">
                {node ? (NODE_KIND_LABELS[node.kind] ?? node.kind) : 'unknown'}
            </LemonTag>
            <div className="font-mono text-xs mt-1.5 truncate">{node?.name ?? fallbackId}</div>
            {columnName ? (
                <div className="font-mono text-[10px] text-muted-alt mt-0.5 truncate">.{columnName}</div>
            ) : null}
        </div>
    )
}
