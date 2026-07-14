import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArchive, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { proposalListLogic } from '../../logics/proposalListLogic'
import { SignalReport } from '../../types'
import { inboxCardRowClassName, useReportArchive } from './useReportArchive'

const PROPOSAL_PRODUCT_LABELS: Record<string, string> = {
    product_analytics: 'Product analytics',
    feature_flags: 'Feature flags',
    error_tracking: 'Error tracking',
    logs: 'Logs',
}

/** A setup-improvement proposal on the inbox cold start. Nothing runs until the user approves. */
export function ProposalCard({ report }: { report: SignalReport }): JSX.Element {
    const { approvingReportId } = useValues(proposalListLogic)
    const { approveProposal, dismissProposal } = useActions(proposalListLogic)

    const cardTitle = report.title?.trim() || 'Setup improvement proposal'
    const productLabel = report.proposal?.product ? PROPOSAL_PRODUCT_LABELS[report.proposal.product] : undefined
    const isApproving = approvingReportId === report.id
    const anotherApprovalInFlight = approvingReportId !== null && !isApproving

    const { isArchiving, onArchiveClick } = useReportArchive({
        reportId: report.id,
        cardTitle,
        report,
        surface: 'list_row',
        onArchive: (reason, note) => dismissProposal(report.id, reason, note),
    })

    return (
        <div className={clsx('relative', inboxCardRowClassName(false, { dashed: true }))}>
            <div className="flex min-w-0 flex-1 items-start gap-3 text-left">
                <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                        <LemonTag type="highlight" size="small" className="shrink-0 select-none">
                            Proposal
                        </LemonTag>
                        <span className="min-w-0 break-words font-semibold text-sm leading-snug text-balance">
                            {cardTitle}
                        </span>
                    </div>

                    {report.summary ? (
                        <p className="min-w-0 break-words text-xs text-secondary leading-snug m-0">{report.summary}</p>
                    ) : null}

                    {productLabel ? (
                        <div className="flex items-center flex-wrap mt-1.5 min-w-0 gap-2.5 text-xs text-tertiary leading-none select-none">
                            <LemonTag size="small">{productLabel}</LemonTag>
                        </div>
                    ) : null}
                </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 shrink-0 @lg:self-stretch @lg:border-l @lg:border-primary @lg:pl-3">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconArchive />}
                    tooltip="Not interested — dismiss this proposal"
                    aria-label="Dismiss this proposal"
                    loading={isArchiving}
                    disabledReason={isApproving ? 'Starting the PR…' : undefined}
                    onClick={onArchiveClick}
                >
                    Dismiss
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPullRequest />}
                    tooltip="Approve: an agent implements this in your repo and opens a draft PR"
                    loading={isApproving}
                    disabledReason={anotherApprovalInFlight ? 'Another proposal is starting' : undefined}
                    onClick={() => approveProposal(report)}
                >
                    Create this PR
                </LemonButton>
            </div>
        </div>
    )
}
