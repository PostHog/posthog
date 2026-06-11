import { useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'
import { RightColumnSection } from './DetailSection'

/**
 * Suggested reviewers for the report, read from the `suggested_reviewers` artefact.
 * Read-only display (avatar, name, GitHub link, relevant commits + reasons). Mirrors desktop's
 * `SuggestedReviewersSection` layout. Add/remove is not ported — see report notes (missing
 * reviewer-write api wrapper).
 */
export function SuggestedReviewersSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportReviewers } = useValues(inboxReportDetailLogic({ reportId: report.id }))

    if (!reportReviewers || reportReviewers.length === 0) {
        return null
    }

    return (
        <RightColumnSection icon={<IconPeople />} title="Reviewers">
            <div className="flex flex-col gap-1.5">
                {reportReviewers.map((reviewer: EnrichedReviewer) => (
                    <ReviewerRow key={reviewer.user?.uuid ?? reviewer.github_login} reviewer={reviewer} />
                ))}
            </div>
        </RightColumnSection>
    )
}

function ReviewerRow({ reviewer }: { reviewer: EnrichedReviewer }): JSX.Element {
    const displayName = reviewer.github_name ?? reviewer.user?.first_name ?? reviewer.github_login
    const reason = reviewer.relevant_commits[0]?.reason ?? null

    return (
        <div className="flex items-start gap-2 rounded px-1.5 py-1.5 transition-colors hover:bg-fill-highlight-50">
            <Tooltip
                title={
                    reviewer.user
                        ? undefined
                        : `${displayName} hasn't connected their GitHub account to PostHog. Ask them to do so in Settings!`
                }
            >
                <span className={!reviewer.user ? 'opacity-75' : undefined}>
                    <PersonDisplay
                        person={{
                            properties: {
                                email: reviewer.user?.email,
                                name: displayName,
                            },
                        }}
                        displayName={displayName}
                        withIcon="xs"
                        noLink
                        noPopover
                    />
                </span>
            </Tooltip>
            <div className="flex flex-col min-w-0 flex-1 gap-0.5">
                <div className="flex items-center gap-2 flex-wrap">
                    {reviewer.github_login && (
                        <Link
                            to={`https://github.com/${reviewer.github_login}`}
                            target="_blank"
                            className="text-xs text-muted hover:text-primary shrink-0"
                        >
                            @{reviewer.github_login}
                        </Link>
                    )}
                    {reviewer.relevant_commits.length > 0 && (
                        <span className="text-[0.6875rem] text-tertiary">
                            {reviewer.relevant_commits.map((commit, i) => (
                                <span key={commit.sha}>
                                    {i > 0 && ', '}
                                    <Tooltip title={commit.reason || undefined}>
                                        <Link
                                            to={commit.url}
                                            target="_blank"
                                            className="font-mono text-tertiary hover:text-primary"
                                        >
                                            {commit.sha.slice(0, 7)}
                                        </Link>
                                    </Tooltip>
                                </span>
                            ))}
                        </span>
                    )}
                </div>
                {reason && <span className="text-[0.6875rem] text-tertiary leading-snug">{reason}</span>}
            </div>
        </div>
    )
}
