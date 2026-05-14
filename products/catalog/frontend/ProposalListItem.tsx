import clsx from 'clsx'

import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { KIND_LABELS, NODE_KIND_LABELS, PROPOSAL_CATEGORIES, Proposal, RELATIONSHIP_KIND_LABELS } from './proposalTypes'

const TAG_TYPE_BY_KIND: Record<Proposal['kind'], LemonTagType> = {
    node_proposed: 'primary',
    node_drift: 'warning',
    relationship_proposed: 'option',
}

interface ProposalListItemProps {
    proposal: Proposal
    selected: boolean
    onClick: () => void
}

export function ProposalListItem({ proposal, selected, onClick }: ProposalListItemProps): JSX.Element {
    const cat = PROPOSAL_CATEGORIES.find((c) => c.key === proposal.kind)
    const { title, summary, confidence } = describeProposal(proposal)

    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'w-full text-left p-3 rounded border transition-colors',
                selected
                    ? 'border-primary-3000 bg-primary-3000-highlight'
                    : 'border-border bg-surface-primary hover:bg-fill-highlight-50'
            )}
        >
            <div className="flex items-start gap-3">
                <span aria-hidden className="text-base leading-6 text-muted-alt w-4 text-center">
                    {cat?.iconLabel ?? '•'}
                </span>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-xs text-muted-alt mb-0.5">
                        <LemonTag type={TAG_TYPE_BY_KIND[proposal.kind]} size="small">
                            {KIND_LABELS[proposal.kind]}
                        </LemonTag>
                        {confidence != null ? (
                            <span className="tabular-nums">{Math.round(confidence * 100)}% confidence</span>
                        ) : null}
                    </div>
                    <div className="font-medium leading-tight truncate">{title}</div>
                    <div className="text-xs text-muted-alt mt-0.5 truncate">{summary}</div>
                </div>
            </div>
        </button>
    )
}

/**
 * Map a real Proposal onto the title/summary/confidence the row needs.
 * Lives here so the dispatcher in ProposalDetail and this row share zero
 * derived-state logic — each pulls what it needs straight from the DTO.
 */
function describeProposal(proposal: Proposal): { title: string; summary: string; confidence: number | null } {
    if (proposal.kind === 'relationship_proposed') {
        const { relationship, sourceNode, targetNode } = proposal
        const kindLabel = RELATIONSHIP_KIND_LABELS[relationship.kind] ?? relationship.kind
        const source = sourceNode?.name ?? '?'
        const target = targetNode?.name ?? '?'
        return {
            title: `${source} ↔ ${target}`,
            summary: `${kindLabel}${relationship.reasoning ? ` · ${relationship.reasoning}` : ''}`,
            confidence: relationship.confidence,
        }
    }
    const { node } = proposal
    const kindLabel = NODE_KIND_LABELS[node.kind] ?? node.kind
    const summaryPieces: string[] = [kindLabel]
    if (node.business_domain) {
        summaryPieces.push(`domain: ${node.business_domain}`)
    }
    if (node.columns.length) {
        summaryPieces.push(`${node.columns.length} col${node.columns.length === 1 ? '' : 's'}`)
    }
    return {
        title: node.name,
        summary: summaryPieces.join(' · '),
        confidence: node.confidence,
    }
}
