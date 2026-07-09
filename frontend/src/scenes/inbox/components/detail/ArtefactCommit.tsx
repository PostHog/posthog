import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { signalsReportArtefactsDiff } from 'products/signals/frontend/generated/api'
import type { CommitDiffResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { CommitContent } from './artefactTypes'
import { DiffBlock } from './DiffBlock'

/**
 * A `commit` artefact: the message, short sha + repo@branch, and a collapsible "View diff" that
 * lazily fetches the commit-vs-parent diff from the backend on first expand. Missing / rewritten
 * commits surface a clean message; oversized diffs show a truncation notice. Mirrors desktop
 * `ArtefactCommit`.
 */
export function ArtefactCommit({
    reportId,
    artefactId,
    content,
}: {
    reportId: string
    artefactId: string
    content: CommitContent
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [expanded, setExpanded] = useState(false)
    const [diff, setDiff] = useState<CommitDiffResponseApi | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // Fetch the diff only once, on first expand — commit diffs are immutable, so there's no reason
    // to refetch. Keyed on artefactId so a recycled component instance refetches for a new commit;
    // `currentTeamId` is a dep so a late-arriving team still triggers the fetch once available.
    useEffect(() => {
        if (!expanded || diff || loading || error || !currentTeamId) {
            return
        }
        setLoading(true)
        let cancelled = false
        signalsReportArtefactsDiff(String(currentTeamId), reportId, artefactId)
            .then((response) => {
                if (!cancelled) {
                    setDiff(response)
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setError("Couldn't load this commit's diff — it may have been rewritten or removed.")
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
    }, [expanded, artefactId, currentTeamId])

    return (
        <div>
            <span className="block text-default text-xs">{content.message}</span>
            <span className="block font-mono text-tertiary text-[11px]">
                {content.commit_sha.slice(0, 12)} · {content.repository}@{content.branch}
            </span>
            {content.note?.trim() ? <span className="block text-secondary text-xs mt-1">{content.note}</span> : null}

            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="mt-1.5 flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-secondary transition-colors hover:bg-fill-highlight-50"
            >
                {expanded ? <IconChevronDown /> : <IconChevronRight />}
                {expanded ? 'Hide diff' : 'View diff'}
            </button>

            {expanded ? (
                <div className="mt-1.5">
                    {loading ? (
                        <div className="flex items-center gap-2 text-[11px] text-tertiary py-1">
                            <Spinner className="size-3" />
                            Fetching diff…
                        </div>
                    ) : error ? (
                        <span className="text-[11px] text-danger">{error}</span>
                    ) : diff && diff.diff.trim() ? (
                        <>
                            <DiffBlock diff={diff.diff} />
                            {diff.truncated ? (
                                <span className="mt-1 block text-[11px] text-tertiary italic">
                                    Diff truncated — open the commit in GitHub for the full change.
                                </span>
                            ) : null}
                        </>
                    ) : (
                        <span className="text-[11px] text-tertiary">No changes recorded for this commit.</span>
                    )}
                </div>
            ) : null}
        </div>
    )
}
