import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconComment, IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'

import type { PullRequestCommentApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

/**
 * A single PR comment: who wrote it and when on one muted line, then the body.
 *
 * The body is clipped until asked for. GitHub bodies arrive with their own headings, tables and code
 * blocks, and a bot-written one can be longer than the report it hangs off — rendered in full they
 * out-shout the report's own summary directly above them. Clipping keeps this section a pointer back
 * to the thread rather than a second place to read it.
 */
function CommentRow({ comment }: { comment: PullRequestCommentApi }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [clipped, setClipped] = useState(false)
    const bodyRef = useRef<HTMLDivElement | null>(null)

    // While collapsed `max-h-24` caps clientHeight, so an overflowing scrollHeight means there is
    // more body to show. Only re-measured when the body changes — once expanded the two are equal.
    useEffect(() => {
        if (bodyRef.current) {
            setClipped(bodyRef.current.scrollHeight > bodyRef.current.clientHeight)
        }
    }, [comment.body])

    return (
        <li className="flex flex-col gap-1 min-w-0">
            <div className="flex items-center gap-2 text-xs text-tertiary min-w-0">
                <span className="shrink-0 font-medium text-secondary">{comment.author ?? 'Unknown'}</span>
                {comment.created_at && <TZLabel time={comment.created_at} />}
                {comment.comment_type === 'review' && comment.path && (
                    <Tooltip title={comment.path}>
                        <span className="truncate">{comment.path}</span>
                    </Tooltip>
                )}
                {comment.url && (
                    <Link
                        to={comment.url}
                        target="_blank"
                        className="ml-auto shrink-0 inline-flex items-center text-tertiary"
                        aria-label="Open comment in GitHub"
                    >
                        <IconExternal className="size-3.5" />
                    </Link>
                )}
            </div>
            {comment.body ? (
                <>
                    <div
                        ref={bodyRef}
                        className={cn('text-sm text-secondary break-words', !expanded && 'max-h-24 overflow-hidden')}
                    >
                        <LemonMarkdown lowKeyHeadings disableImages>
                            {comment.body}
                        </LemonMarkdown>
                    </div>
                    {clipped && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={() => setExpanded(!expanded)}
                            aria-expanded={expanded}
                            className="self-start -ml-2"
                        >
                            {expanded ? 'Show less' : 'Show more'}
                        </LemonButton>
                    )}
                </>
            ) : (
                <p className="m-0 text-sm text-tertiary italic">No content.</p>
            )}
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
                <ul className="flex flex-col gap-3 m-0 p-0 list-none">
                    {prComments.map((comment) => (
                        <CommentRow key={comment.id} comment={comment} />
                    ))}
                </ul>
            )}
        </DetailSection>
    )
}
