import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

import { KIND_LABELS, PROPOSAL_CATEGORIES, Proposal } from './proposalTypes'

const TAG_TYPE_BY_KIND: Record<
    Proposal['kind'],
    'primary' | 'warning' | 'danger' | 'success' | 'highlight' | 'completion' | 'option'
> = {
    new_definition: 'primary',
    drift: 'warning',
    duplicate: 'highlight',
    schema_sync: 'completion',
    relationship: 'option',
    metadata: 'success',
    question: 'danger',
}

interface ProposalListItemProps {
    proposal: Proposal
    selected: boolean
    onClick: () => void
}

export function ProposalListItem({ proposal, selected, onClick }: ProposalListItemProps): JSX.Element {
    const cat = PROPOSAL_CATEGORIES.find((c) => c.key === proposal.kind)
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
                        <span className="tabular-nums">{Math.round(proposal.confidence * 100)}% confidence</span>
                        <span aria-hidden>·</span>
                        <span>{formatAge(proposal.ageHours)}</span>
                    </div>
                    <div className="font-medium leading-tight truncate">{proposal.title}</div>
                    <div className="text-xs text-muted-alt mt-0.5 truncate">{proposal.summary}</div>
                </div>
            </div>
        </button>
    )
}

function formatAge(hours: number): string {
    if (hours < 1) {
        return 'just now'
    }
    if (hours < 24) {
        return `${Math.round(hours)}h ago`
    }
    const days = Math.round(hours / 24)
    return `${days}d ago`
}
