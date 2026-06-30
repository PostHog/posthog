import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { signalsReportArtefactsDiff } from 'products/signals/frontend/generated/api'
import type { CommitDiffResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { CommitContent } from './artefactTypes'
import { PullRequestDiffView } from './PullRequestDiffView'

/**
 * Full-width modal showing the report's branch diff against the repository default branch, rendered
 * GitHub-style and read-only. The diff is fetched from the latest `commit` artefact's branch (its
 * current tip), so it reflects the latest state of the work — not just the recorded commit. Refetched
 * on each open since the branch keeps moving after the commit was recorded (follow-up pushes, PR
 * babysitting), which would stale a cached diff.
 */
export function PullRequestDiffModal({
    reportId,
    artefactId,
    commit,
    prUrl,
    prLabel,
    isOpen,
    onClose,
}: {
    reportId: string
    artefactId: string
    commit: CommitContent
    /** PR files URL, when the report has a shipped implementation PR — surfaces an "Open in GitHub" action. */
    prUrl?: string | null
    /** `repoSlug#number` label for the PR, used as the modal title when present. */
    prLabel?: string | null
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [diff, setDiff] = useState<CommitDiffResponseApi | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!isOpen || !currentTeamId) {
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
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen, artefactId, currentTeamId])

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={prLabel || 'Changed files'}
            description={
                <span className="font-mono text-xs text-tertiary">
                    {commit.repository}@{commit.branch}
                </span>
            }
            width="min(95vw, 72rem)"
            footer={
                prUrl ? (
                    <LemonButton type="secondary" to={prUrl} targetBlank sideIcon={<IconExternal />}>
                        Open in GitHub
                    </LemonButton>
                ) : undefined
            }
        >
            <div className="max-h-[70vh] overflow-auto">
                {loading ? (
                    <div className="flex items-center justify-center gap-2 py-10 text-sm text-tertiary">
                        <Spinner className="size-4" />
                        Loading diff…
                    </div>
                ) : error ? (
                    <p className="m-0 py-6 text-sm text-danger">{error}</p>
                ) : diff ? (
                    <PullRequestDiffView diff={diff.diff} truncated={diff.truncated} />
                ) : null}
            </div>
        </LemonModal>
    )
}
