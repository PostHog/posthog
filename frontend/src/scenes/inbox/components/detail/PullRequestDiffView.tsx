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

    // Distinguish a parse failure from a genuinely empty diff — otherwise both render the same
    // "no changes" message, hiding from the user that their real changes failed to parse.
    const [parseFailed, files] = useMemo<[boolean, FileDiffMetadata[]]>(() => {
        if (!diff.trim()) {
            return [false, []]
        }
        try {
            return [false, parsePatchFiles(diff, cacheKey).flatMap((patch) => patch.files)]
        } catch {
            return [true, []]
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

    if (parseFailed) {
        return <p className="m-0 text-sm text-danger">Couldn't parse this diff — it may be in an unexpected format.</p>
    }

    if (files.length === 0) {
        return <p className="m-0 text-sm text-tertiary">No file changes to display for this branch.</p>
    }

    return (
        <div className="flex flex-col gap-3">
            {files.map((file) => (
                // Card chrome around each file so the diff sits in PostHog's visual language (bordered,
                // rounded surface); @pierre/diffs renders its own header + syntax-highlighted body inside.
                <div
                    key={`${file.name}-${file.cacheKey ?? file.newObjectId ?? ''}`}
                    className="overflow-hidden rounded-lg border border-primary bg-surface-primary"
                >
                    <FileDiff fileDiff={file} options={options} disableWorkerPool />
                </div>
            ))}
            {truncated ? (
                <p className="m-0 text-xs text-tertiary italic">
                    Diff truncated — open the pull request in GitHub for the full change.
                </p>
            ) : null}
        </div>
    )
}
