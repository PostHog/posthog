import { useValues } from 'kea'
import { useState } from 'react'

import { IconGitBranch } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { CommitContent } from './artefactTypes'
import { PullRequestDiffView } from './PullRequestDiffView'

const DIFF_STYLE_OPTIONS = [
    { value: 'unified' as const, label: 'Unified' },
    { value: 'split' as const, label: 'Split' },
]

/**
 * "Files changed" tab body: the report's branch diff against the repository default branch, rendered
 * GitHub-style and read-only. The tab already labels this, so the panel leads with a compact toolbar
 * (branch context on the left, unified/split toggle on the right) rather than a titled section. The
 * diff itself is loaded by `inboxReportDetailLogic` (keyed to the report, cascading off the artefact
 * load) — this component just renders the current state, tracking the branch tip as the work moves.
 */
export function PullRequestDiffPanel({ report, commit }: { report: SignalReport; commit: CommitContent }): JSX.Element {
    const { reportDiff, reportDiffError } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const [diffStyle, setDiffStyle] = useState<'unified' | 'split'>('unified')

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0">
                <Tooltip title={`Comparing ${commit.repository}@${commit.branch} against the default branch`}>
                    <LemonTag type="muted" className="font-mono min-w-0">
                        <IconGitBranch className="shrink-0" />
                        <span className="truncate">{commit.branch}</span>
                    </LemonTag>
                </Tooltip>
                <div className="flex-1" />
                <LemonSegmentedButton
                    size="small"
                    value={diffStyle}
                    onChange={setDiffStyle}
                    options={DIFF_STYLE_OPTIONS}
                />
            </div>
            {reportDiffError ? (
                <p className="m-0 py-4 text-sm text-danger">{reportDiffError}</p>
            ) : reportDiff ? (
                <PullRequestDiffView
                    diff={reportDiff.diff}
                    truncated={reportDiff.truncated}
                    cacheKey={commit.commit_sha}
                    diffStyle={diffStyle}
                />
            ) : (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-8 w-full" />
                    <LemonSkeleton className="h-24 w-full" />
                </div>
            )}
        </div>
    )
}
