import { useValues } from 'kea'
import { useState } from 'react'

import { IconCode, IconGitBranch } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { CommitContent } from './artefactTypes'
import { DetailSection } from './DetailSection'
import { PullRequestDiffView } from './PullRequestDiffView'

const DIFF_STYLE_OPTIONS = [
    { value: 'unified' as const, label: 'Unified' },
    { value: 'split' as const, label: 'Split' },
]

/**
 * Full-width "Files changed" section: the report's branch diff against the repository default branch,
 * rendered GitHub-style and read-only. The diff itself is loaded by `inboxReportDetailLogic` (keyed to
 * the report, cascading off the artefact load) — this component just renders the current state. The
 * diff reflects the latest `commit` artefact's branch tip, so it tracks the work as the branch moves.
 */
export function PullRequestDiffPanel({ report, commit }: { report: SignalReport; commit: CommitContent }): JSX.Element {
    const { reportDiff, reportDiffError } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const [diffStyle, setDiffStyle] = useState<'unified' | 'split'>('unified')

    return (
        <DetailSection
            icon={<IconCode />}
            title="Files changed"
            afterTitle={
                <Tooltip title={`Comparing ${commit.repository}@${commit.branch} against the default branch`}>
                    <LemonTag type="muted" className="font-mono">
                        <IconGitBranch className="shrink-0" />
                        <span className="truncate">{commit.branch}</span>
                    </LemonTag>
                </Tooltip>
            }
            rightSlot={
                <LemonSegmentedButton
                    size="small"
                    value={diffStyle}
                    onChange={setDiffStyle}
                    options={DIFF_STYLE_OPTIONS}
                />
            }
        >
            <div className="flex flex-col gap-3">
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
        </DetailSection>
    )
}
