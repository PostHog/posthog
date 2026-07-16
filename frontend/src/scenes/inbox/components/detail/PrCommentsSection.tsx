import { useValues } from 'kea'

import { IconComment, IconExternal } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { PullRequestCommentApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

/** A single PR comment row: avatar, author, relative time, optional file path, then the markdown body. */
function CommentRow({ comment }: { comment: PullRequestCommentApi }): JSX.Element {
    return (
        <li className="flex gap-2.5 min-w-0">
            {comment.author_avatar_url ? (
                <img
                    src={comment.author_avatar_url}
                    alt={comment.author ?? 'author'}
                    className="size-6 shrink-0 rounded-full bg-fill-highlight-50"
                    loading="lazy"
                />
            ) : (
                <span className="size-6 shrink-0 rounded-full bg-fill-highlight-100" aria-hidden />
            )}
            <div className="flex flex-col gap-1 min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary min-w-0">
                    <span className="font-semibold text-secondary">{comment.author ?? 'Unknown'}</span>
                    {comment.created_at && <TZLabel time={comment.created_at} />}
                    {comment.comment_type === 'review' && comment.path && (
                        <Tooltip title={comment.path}>
                            <LemonTag type="muted" className="font-mono max-w-[16rem]">
                                <span className="truncate">{comment.path}</span>
                            </LemonTag>
                        </Tooltip>
                    )}
                    {comment.url && (
                        <Link to={comment.url} target="_blank" className="inline-flex items-center text-tertiary">
                            <IconExternal className="size-3.5" />
                        </Link>
                    )}
                </div>
                {comment.body ? (
                    <LemonMarkdown
                        className="text-sm text-secondary leading-relaxed break-words overflow-auto"
                        disableImages
                    >
                        {comment.body}
                    </LemonMarkdown>
                ) : (
                    <p className="m-0 text-sm text-tertiary italic">No content.</p>
                )}
            </div>
        </li>
    )
}

/**
 * "Comments" section for a report's implementation PR: the PR's conversation comments and inline
 * review comments merged chronologically. Read-only mirror of the GitHub thread — each comment
 * links out to GitHub. Collapsed by default so it doesn't crowd the overview.
 */
export function PrCommentsSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { prComments, prCommentsLoading, prCommentsError } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // Never loaded yet: show a skeleton. Loaded-but-empty: nothing to show, so drop the section.
    if (prComments === null) {
        if (!prCommentsLoading && !prCommentsError) {
            return null
        }
    } else if (prComments.length === 0 && !prCommentsError) {
        return null
    }

    return (
        <DetailSection
            icon={<IconComment />}
            title="Comments"
            collapsible
            defaultCollapsed
            meta={
                prComments && prComments.length > 0 ? (
                    <span className="text-[0.6875rem] text-tertiary tabular-nums">
                        {prComments.length} comment{prComments.length === 1 ? '' : 's'}
                    </span>
                ) : undefined
            }
        >
            {prCommentsError ? (
                <p className="m-0 py-2 text-sm text-danger">{prCommentsError}</p>
            ) : prComments === null ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-10 w-full" />
                    <LemonSkeleton className="h-10 w-4/5" />
                </div>
            ) : (
                <ul className="flex flex-col gap-4 m-0 p-0 list-none">
                    {prComments.map((comment) => (
                        <CommentRow key={comment.id} comment={comment} />
                    ))}
                </ul>
            )}
        </DetailSection>
    )
}
