import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCode, IconGitBranch } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { signalsReportArtefactsDiff } from 'products/signals/frontend/generated/api'
import type { CommitDiffResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { CommitContent } from './artefactTypes'
import { DetailSection } from './DetailSection'
import { PullRequestDiffView } from './PullRequestDiffView'

const DIFF_STYLE_OPTIONS = [
    { value: 'unified' as const, label: 'Unified' },
    { value: 'split' as const, label: 'Split' },
]

/**
 * Full-width "Files changed" section: the report's branch diff against the repository default branch,
 * rendered GitHub-style and read-only. The diff is fetched from the latest `commit` artefact's branch
 * (its current tip), so it reflects the latest state of the work — not just the recorded commit. It
 * lives at the bottom of the report detail, always visible (Graphite-style), and loads on mount.
 */
export function PullRequestDiffPanel({
    reportId,
    artefactId,
    commit,
}: {
    reportId: string
    artefactId: string
    commit: CommitContent
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [diff, setDiff] = useState<CommitDiffResponseApi | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [diffStyle, setDiffStyle] = useState<'unified' | 'split'>('unified')

    useEffect(() => {
        if (!currentTeamId) {
            return
        }
        setLoading(true)
        setError(null)
        let cancelled = false
        signalsReportArtefactsDiff(String(currentTeamId), reportId, artefactId)
            .then((response) => {
                if (!cancelled) {
                    setDiff(response)
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setError("Couldn't load the diff — the branch may have been merged, deleted, or rewritten.")
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })
        return () => {
            cancelled = true
        }
    }, [reportId, artefactId, currentTeamId])

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
                {loading ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-8 w-full" />
                        <LemonSkeleton className="h-24 w-full" />
                    </div>
                ) : error ? (
                    <p className="m-0 py-4 text-sm text-danger">{error}</p>
                ) : diff ? (
                    <PullRequestDiffView
                        diff={diff.diff}
                        truncated={diff.truncated}
                        cacheKey={commit.commit_sha}
                        diffStyle={diffStyle}
                    />
                ) : null}
            </div>
        </DetailSection>
    )
}
