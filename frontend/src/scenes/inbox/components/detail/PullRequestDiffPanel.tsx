import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconGitBranch } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { CommitContent } from './artefactTypes'
import { PullRequestDiffView, summarizeDiff } from './PullRequestDiffView'

const DIFF_STYLE_OPTIONS = [
    { value: 'unified' as const, label: 'Unified' },
    { value: 'split' as const, label: 'Split' },
]

/**
 * The diff's +/- line counts, shown in the "Files changed" tab label beside the branch so the size of
 * the change reads at a glance even while the tab is collapsed. Renders nothing until the diff loads
 * (or if it's empty). Reads the same `reportDiff` the panel body does — no extra fetch.
 */
export function PullRequestDiffStat({
    report,
    commit,
}: {
    report: SignalReport
    commit: CommitContent
}): JSX.Element | null {
    const { reportDiff, reportDiffError } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const summary = useMemo(
        () => (reportDiff ? summarizeDiff(reportDiff.diff, commit.commit_sha) : null),
        [reportDiff, commit.commit_sha]
    )
    // Reserve the stat's space while the patch is still loading, so it doesn't pop into the tab label —
    // but on a load error there's no stat to wait for, so drop it (the panel body shows the error).
    if (!reportDiff) {
        return reportDiffError ? null : <PullRequestDiffStatSkeleton />
    }
    if (!summary || (summary.additions === 0 && summary.deletions === 0)) {
        return null
    }
    return (
        <span className="flex shrink-0 items-center gap-1.5 font-mono text-xs tabular-nums">
            {summary.deletions > 0 && <span className="text-danger">-{summary.deletions}</span>}
            {summary.additions > 0 && <span className="text-success">+{summary.additions}</span>}
        </span>
    )
}

/** Mini placeholders for the "Files changed" tab label, shown from the moment we know the report has a
 * PR until the commit artefact (branch) and its diff (size) load — so the tab bar appears immediately
 * instead of a beat later. */
export function PullRequestDiffStatSkeleton(): JSX.Element {
    return <LemonSkeleton className="h-3.5 w-9 rounded" />
}

export function PullRequestBranchTagSkeleton(): JSX.Element {
    return <LemonSkeleton className="h-[1.375rem] w-24 rounded" />
}

/**
 * "Files changed" tab body shown before the commit artefact resolves: a diff skeleton while the branch
 * is still loading, or a fallback to GitHub if the artefacts finished loading without a diffable commit.
 */
export function PullRequestDiffPending({ artefactsLoaded }: { artefactsLoaded: boolean }): JSX.Element {
    if (artefactsLoaded) {
        return (
            <p className="m-0 py-4 text-sm text-tertiary">
                The diff isn't available here. Open the pull request on GitHub to review the changes.
            </p>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            <LemonSkeleton className="h-8 w-full" />
            <LemonSkeleton className="h-24 w-full" />
        </div>
    )
}

/**
 * The report's branch as a git-branch tag. Rendered in the "Files changed" tab label (so the tab
 * signals there's code behind it, GitHub-style) — inside the LemonTabs active tab it picks up the
 * accent color for free.
 */
export function PullRequestBranchTag({ commit }: { commit: CommitContent }): JSX.Element {
    return (
        <Tooltip title={`Comparing ${commit.repository}@${commit.branch} against the default branch`}>
            <LemonTag type="muted" className="font-mono min-w-0">
                <IconGitBranch className="shrink-0" />
                <span className="truncate">{commit.branch}</span>
            </LemonTag>
        </Tooltip>
    )
}

/**
 * "Files changed" tab body: the report's branch diff against the repository default branch, rendered
 * GitHub-style and read-only. The tab carries the branch tag; this toolbar balances diff stats on the
 * left with the unified/split toggle on the right. The diff itself is loaded by `inboxReportDetailLogic`
 * (keyed to the report, cascading off the artefact load) — this component just renders the current
 * state, tracking the branch tip as the work moves.
 */
export function PullRequestDiffPanel({ report, commit }: { report: SignalReport; commit: CommitContent }): JSX.Element {
    const logicProps = useMemo(() => ({ reportId: report.id, report }), [report])
    const { reportDiff, reportDiffError } = useValues(inboxReportDetailLogic(logicProps))
    const [diffStyle, setDiffStyle] = useState<'unified' | 'split'>('unified')
    const diffSummary = useMemo(
        () => (reportDiff ? summarizeDiff(reportDiff.diff, commit.commit_sha) : null),
        [reportDiff, commit.commit_sha]
    )

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3 min-w-0">
                <DiffToolbarSummary commit={commit} diffSummary={diffSummary} />
                <LemonSegmentedButton
                    size="small"
                    value={diffStyle}
                    onChange={setDiffStyle}
                    options={DIFF_STYLE_OPTIONS}
                    className="shrink-0"
                />
            </div>
            {reportDiffError ? (
                <p className="m-0 py-4 text-sm text-danger">{reportDiffError}</p>
            ) : reportDiff ? (
                <>
                    <PullRequestDiffView
                        diff={reportDiff.diff}
                        truncated={reportDiff.truncated}
                        cacheKey={commit.commit_sha}
                        diffStyle={diffStyle}
                    />
                </>
            ) : (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-8 w-full" />
                    <LemonSkeleton className="h-24 w-full" />
                </div>
            )}
        </div>
    )
}

/** Left side of the diff toolbar — repo context while loading, GitHub-style stats once the patch lands. */
function DiffToolbarSummary({
    commit,
    diffSummary,
}: {
    commit: CommitContent
    diffSummary: ReturnType<typeof summarizeDiff>
}): JSX.Element {
    if (diffSummary) {
        const fileLabel = diffSummary.fileCount === 1 ? '1 file changed' : `${diffSummary.fileCount} files changed`

        return (
            // The +/- line stat lives in the "Files changed" tab label now, so the toolbar carries the file count.
            <div className="flex min-w-0 items-center gap-2 text-sm">
                <span className="truncate text-secondary">{fileLabel}</span>
            </div>
        )
    }

    return (
        <span
            className="min-w-0 truncate font-mono text-xs text-tertiary"
            title={`Comparing ${commit.repository}@${commit.branch} against the default branch`}
        >
            {commit.repository}
            <span className="opacity-70"> · vs default branch</span>
        </span>
    )
}
