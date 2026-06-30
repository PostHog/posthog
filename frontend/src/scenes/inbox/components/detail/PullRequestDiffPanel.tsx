import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { signalsReportArtefactsDiff } from 'products/signals/frontend/generated/api'
import type { CommitDiffResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { CommitContent } from './artefactTypes'
import { PullRequestDiffView } from './PullRequestDiffView'

/**
 * "Files changed" tab body: the report's branch diff against the repository default branch, rendered
 * GitHub-style and read-only. The diff is fetched from the latest `commit` artefact's branch (its
 * current tip), so it reflects the latest state of the work — not just the recorded commit. Fetched
 * on mount; since this lives behind a tab, that means it loads lazily when the tab is first opened,
 * and refetches if the tab is re-opened (the branch keeps moving after the commit was recorded).
 */
export function PullRequestDiffPanel({
    reportId,
    artefactId,
    commit,
    prUrl,
}: {
    reportId: string
    artefactId: string
    commit: CommitContent
    /** PR files URL, when the report has a shipped implementation PR — surfaces an "Open in GitHub" action. */
    prUrl?: string | null
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [diff, setDiff] = useState<CommitDiffResponseApi | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

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
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className="font-mono text-xs text-tertiary truncate">
                    {commit.repository}@{commit.branch}
                </span>
                {prUrl ? (
                    <LemonButton type="secondary" size="small" to={prUrl} targetBlank sideIcon={<IconExternal />}>
                        Open in GitHub
                    </LemonButton>
                ) : null}
            </div>
            {loading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-tertiary">
                    <Spinner className="size-4" />
                    Loading diff…
                </div>
            ) : error ? (
                <p className="m-0 py-6 text-sm text-danger">{error}</p>
            ) : diff ? (
                <PullRequestDiffView diff={diff.diff} truncated={diff.truncated} cacheKey={commit.commit_sha} />
            ) : null}
        </div>
    )
}
