import { useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ReviewCommentEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { CommitContent } from './artefactTypes'
import { DetailSection } from './DetailSection'

// GitHub review verdicts → LemonTag intent. A COMMENTED review (or a plain comment) stays muted.
const REVIEW_STATE_TAG: Record<string, { type: 'success' | 'danger' | 'muted'; label: string }> = {
    APPROVED: { type: 'success', label: 'Approved' },
    CHANGES_REQUESTED: { type: 'danger', label: 'Changes requested' },
    COMMENTED: { type: 'muted', label: 'Commented' },
}

/** A single review / inline comment / conversation comment row. */
function ReviewCommentRow({ entry }: { entry: ReviewCommentEntryApi }): JSX.Element {
    const stateTag = entry.review_state ? REVIEW_STATE_TAG[entry.review_state] : undefined

    const header = (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span className="font-semibold text-primary">{entry.author ?? 'Unknown'}</span>
            {stateTag && (
                <LemonTag type={stateTag.type} size="small">
                    {stateTag.label}
                </LemonTag>
            )}
            {entry.path && (
                <LemonTag type="muted" size="small" className="font-mono max-w-full min-w-0">
                    <span className="truncate block">
                        {entry.path}
                        {entry.line != null ? `:${entry.line}` : ''}
                    </span>
                </LemonTag>
            )}
            {entry.created_at && <TZLabel time={entry.created_at} className="text-tertiary" />}
        </div>
    )

    return (
        <div className="flex flex-col gap-1.5 rounded border border-border-light p-3">
            {entry.html_url ? (
                <Link to={entry.html_url} target="_blank" className="w-fit no-underline hover:opacity-80">
                    {header}
                </Link>
            ) : (
                header
            )}
            {entry.body.trim() ? (
                <LemonMarkdown className="text-xs text-secondary leading-normal" disableImages>
                    {entry.body}
                </LemonMarkdown>
            ) : (
                <span className="text-xs text-tertiary italic">No comment body.</span>
            )}
        </div>
    )
}

/**
 * Full-width "Review comments" section: the review conversation on the report's implementation PR —
 * submitted reviews (approvals / change requests / comments), inline diff-thread comments (with
 * file + line), and top-level conversation comments. Loaded by `inboxReportDetailLogic` (keyed to the
 * report, cascading off the latest commit artefact) — this component just renders the current state.
 */
export function PullRequestReviewCommentsSection({
    report,
    commit,
}: {
    report: SignalReport
    commit: CommitContent
}): JSX.Element {
    const { reportReviewComments, reportReviewCommentsError } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const comments = reportReviewComments?.comments ?? null
    const truncated = reportReviewComments?.truncated ?? false

    return (
        <DetailSection
            icon={<IconChat />}
            title="Review comments"
            collapsible
            afterTitle={
                <LemonTag type="muted" className="font-mono">
                    <span className="truncate">{commit.branch}</span>
                </LemonTag>
            }
        >
            <div className="flex flex-col gap-3">
                {reportReviewCommentsError ? (
                    <p className="m-0 py-4 text-sm text-danger">{reportReviewCommentsError}</p>
                ) : comments === null ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-16 w-full" />
                        <LemonSkeleton className="h-16 w-full" />
                    </div>
                ) : comments.length === 0 ? (
                    <p className="m-0 py-4 text-sm text-tertiary">No review comments yet</p>
                ) : (
                    <>
                        {comments.map((entry, index) => (
                            <ReviewCommentRow key={entry.html_url ?? index} entry={entry} />
                        ))}
                        {truncated && (
                            <p className="m-0 text-xs text-tertiary italic">
                                This pull request has more activity than shown here. Open it on GitHub for the full
                                conversation.
                            </p>
                        )}
                    </>
                )}
            </div>
        </DetailSection>
    )
}
