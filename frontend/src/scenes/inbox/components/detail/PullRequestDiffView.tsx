import { type FileDiffMetadata, type FileDiffOptions, parsePatchFiles } from '@pierre/diffs'
import { FileDiff } from '@pierre/diffs/react'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

// Shiki bundled themes that read closest to GitHub's diff view; Pierre swaps between them based on
// `themeType`, which we drive off PostHog's own light/dark state.
const DIFF_THEME = { light: 'github-light', dark: 'github-dark' } as const

/**
 * Read-only, GitHub-style rendering of a unified diff string (the branch-vs-default-branch patch the
 * backend returns for a `commit` artefact). Each file in the patch is rendered with `@pierre/diffs`,
 * which gives Shiki syntax highlighting, file headers, and hunk expansion out of the box. Inspection
 * only — no commenting. The worker pool is disabled so highlighting runs without a separately-served
 * worker bundle; diffs are size-bounded by the backend (see `truncated`), so main-thread is fine.
 */
export function PullRequestDiffView({
    diff,
    truncated,
    cacheKey,
    diffStyle = 'unified',
}: {
    diff: string
    truncated: boolean
    /** Stable prefix for Pierre's render cache — pass the commit sha so re-renders reuse highlighting. */
    cacheKey?: string
    /** Unified (stacked) or split (side-by-side) layout, like GitHub's diff view toggle. */
    diffStyle?: 'unified' | 'split'
}): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const files = useMemo<FileDiffMetadata[]>(() => {
        if (!diff.trim()) {
            return []
        }
        try {
            return parsePatchFiles(diff, cacheKey).flatMap((patch) => patch.files)
        } catch {
            return []
        }
    }, [diff, cacheKey])

    const options = useMemo<FileDiffOptions<undefined>>(
        () => ({
            theme: DIFF_THEME,
            themeType: isDarkModeOn ? 'dark' : 'light',
            diffStyle,
            stickyHeader: true,
            overflow: 'scroll',
        }),
        [isDarkModeOn, diffStyle]
    )

    if (files.length === 0) {
        return <p className="m-0 text-sm text-tertiary">No file changes to display for this branch.</p>
    }

    return (
        <div className="flex flex-col gap-3">
            {files.map((file) => (
                <FileDiff
                    key={`${file.name}-${file.cacheKey ?? file.newObjectId ?? ''}`}
                    fileDiff={file}
                    options={options}
                    disableWorkerPool
                />
            ))}
            {truncated ? (
                <p className="m-0 text-[12px] text-tertiary italic">
                    Diff truncated — open the pull request in GitHub for the full change.
                </p>
            ) : null}
        </div>
    )
}
