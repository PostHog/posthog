import { useActions, useValues } from 'kea'

import { Badge, Button } from '@posthog/quill'

import { CatalogTableRow, ProposalDecision, hasPendingProposal } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'
import { CertificationStatusTag, certificationStatusTag } from '../certificationStatusTag'
import { CatalogReviewAccess } from './CatalogReviewAccess'

const TRUST_BADGE_VARIANTS: Record<CertificationStatusTag['type'], 'success' | 'warning' | 'default'> = {
    success: 'success',
    warning: 'warning',
    muted: 'default',
}

const DECISION_LABELS: Record<ProposalDecision, string> = {
    accept: 'Accept',
    reject: 'Reject',
}

const DECISIONS: ProposalDecision[] = ['accept', 'reject']

function ProposalReviewButtons({ row }: { row: CatalogTableRow }): JSX.Element {
    const { reviewingRows, bulkActionInFlight } = useValues(catalogTablesLogic)
    const { reviewProposals } = useActions(catalogTablesLogic)
    const reviewing = reviewingRows[row.key]
    const busyReason = reviewing || bulkActionInFlight ? 'Saving the last change' : undefined

    return (
        <div className="flex items-center gap-1">
            {DECISIONS.map((decision) => (
                <CatalogReviewAccess key={decision}>
                    <Button
                        variant={decision === 'accept' ? 'outline' : 'default'}
                        size="xs"
                        loading={reviewing === decision}
                        disabledReason={reviewing === decision ? undefined : busyReason}
                        onClick={() => reviewProposals([row.key], decision, 'inline')}
                        data-attr={`data-catalog-tables-inline-${decision}`}
                    >
                        {DECISION_LABELS[decision]}
                    </Button>
                </CatalogReviewAccess>
            ))}
        </div>
    )
}

export function CatalogTableTrust({ row }: { row: CatalogTableRow }): JSX.Element | null {
    if (!row.certification) {
        return null
    }
    const tag = certificationStatusTag(row.certification)
    return (
        <div className="flex flex-wrap items-center gap-1">
            <Badge variant={TRUST_BADGE_VARIANTS[tag.type]}>{tag.label}</Badge>
            {hasPendingProposal(row) && <ProposalReviewButtons row={row} />}
        </div>
    )
}
