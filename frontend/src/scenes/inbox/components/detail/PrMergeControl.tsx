import { useActions, useValues } from 'kea'

import { IconCheck, IconClock, IconExternal, IconGithub } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'

/**
 * The primary merge button for a report's implementation PR (the "Open in GitHub" link lives separately
 * in the header). Its behavior derives from the PR's live merge readiness, the same state GitHub's own
 * merge button reads: "Merge now" when green, "Merge when green" (arms auto-merge) when checks are
 * pending, or a precise disabled reason otherwise. Agent PRs open as drafts, which can't merge from
 * here, so a draft becomes a "Merge draft in GitHub" link. Merges act as the user via their personal
 * GitHub connection. Returns null when there's nothing actionable to show.
 */
export function PrMergeControl({
    report,
    githubUrl,
    githubTooltip,
}: {
    report: SignalReport
    githubUrl: string
    githubTooltip?: string
}): JSX.Element | null {
    const logicProps = { reportId: report.id, report }
    const { prMergeReadiness, prMergeReadinessLoading, merging, hasPersonalGithub } = useValues(
        inboxReportDetailLogic(logicProps)
    )
    const { mergePr, armAutoMerge, cancelAutoMerge, approveAndMerge } = useActions(inboxReportDetailLogic(logicProps))

    const mergeNow = (props: { disabledReason?: string; onClick?: () => void; tooltip?: string }): JSX.Element => (
        <LemonButton type="primary" size="small" loading={merging} {...props}>
            Merge now
        </LemonButton>
    )

    // Draft: agent PRs open as drafts, which can't merge from PostHog – a link straight to GitHub.
    if (
        prMergeReadiness &&
        (prMergeReadiness.pr_state === 'draft' || prMergeReadiness.merge_state_status === 'draft')
    ) {
        return (
            <LemonButton
                type="primary"
                size="small"
                sideIcon={<IconExternal />}
                to={githubUrl}
                targetBlank
                tooltip={githubTooltip}
            >
                Merge draft in GitHub
            </LemonButton>
        )
    }

    if (!prMergeReadiness) {
        return prMergeReadinessLoading ? mergeNow({ disabledReason: 'Checking merge status…' }) : null
    }

    if (prMergeReadiness.pr_state === 'merged') {
        return (
            <LemonTag type="success" icon={<IconCheck />}>
                Merged
            </LemonTag>
        )
    }
    if (prMergeReadiness.pr_state === 'closed') {
        return <LemonTag type="muted">Closed</LemonTag>
    }

    if (!hasPersonalGithub) {
        return (
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconGithub />}
                to={urls.settings('user-personal-integrations')}
                targetBlank
            >
                Connect GitHub to merge
            </LemonButton>
        )
    }

    if (prMergeReadiness.auto_merge_enabled) {
        return (
            <div className="flex items-center gap-1.5">
                <LemonTag type="highlight" icon={<IconClock />}>
                    Auto-merge armed
                </LemonTag>
                <LemonButton type="tertiary" size="small" onClick={cancelAutoMerge} loading={merging}>
                    Cancel
                </LemonButton>
            </div>
        )
    }

    if (prMergeReadiness.merge_state_status === 'unknown' && prMergeReadiness.mergeable === null) {
        return mergeNow({ disabledReason: 'Checking if this can merge…' })
    }
    if (prMergeReadiness.merge_state_status === 'dirty' || prMergeReadiness.mergeable === false) {
        return mergeNow({ disabledReason: 'Resolve the merge conflicts on GitHub first' })
    }
    if (prMergeReadiness.merge_state_status === 'behind') {
        return mergeNow({ disabledReason: 'The branch is behind its base – update it on GitHub first' })
    }
    if (prMergeReadiness.merge_state_status === 'clean' || prMergeReadiness.merge_state_status === 'unstable') {
        return mergeNow({
            onClick: mergePr,
            tooltip:
                prMergeReadiness.merge_state_status === 'unstable' ? 'Some non-required checks are failing' : undefined,
        })
    }
    if (prMergeReadiness.merge_state_status === 'blocked' || prMergeReadiness.merge_state_status === 'has_hooks') {
        if (prMergeReadiness.review_decision === 'changes_requested') {
            return mergeNow({ disabledReason: 'Changes were requested – address them first' })
        }
        if (prMergeReadiness.ci_status === 'failing') {
            return mergeNow({ disabledReason: 'Required checks are failing' })
        }
        // When a required review is the only blocker, approve as the user then merge in one gesture.
        if (prMergeReadiness.review_decision === 'review_required') {
            return (
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={approveAndMerge}
                    loading={merging}
                    tooltip={
                        prMergeReadiness.ci_status === 'pending'
                            ? 'Approves the PR in GitHub, then merges once checks pass'
                            : 'Approves the PR in GitHub, then merges it'
                    }
                >
                    Approve and merge
                </LemonButton>
            )
        }
        if (prMergeReadiness.ci_status === 'pending') {
            return prMergeReadiness.auto_merge_allowed ? (
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={armAutoMerge}
                    loading={merging}
                    tooltip="Merges automatically once required checks pass"
                >
                    Merge when green
                </LemonButton>
            ) : (
                mergeNow({ disabledReason: "Waiting on checks – auto-merge isn't enabled for this repo" })
            )
        }
        return mergeNow({ disabledReason: 'Branch protection is blocking this merge' })
    }

    // Unknown/other state – let the user try and surface any GitHub error rather than dead-ending.
    return mergeNow({ onClick: mergePr })
}
