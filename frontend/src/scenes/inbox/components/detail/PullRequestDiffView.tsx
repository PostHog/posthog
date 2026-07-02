import { type ChangeTypes, type FileDiffMetadata, type FileDiffOptions, parsePatchFiles } from '@pierre/diffs'
import { FileDiff } from '@pierre/diffs/react'
import { useValues } from 'kea'
import { ReactNode, useMemo } from 'react'

import { IconArrowRight, IconMinus, IconPencil, IconPlus } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation/themeLogic'

// Shiki bundled themes that read closest to GitHub's diff view; Pierre swaps between them based on
// `themeType`, which we drive off PostHog's own light/dark state.
const DIFF_THEME = { light: 'github-light', dark: 'github-dark' } as const

// Pierre's own file header uses a prose-font filename and an unlabelled glyph. We render our own header
// with a monospace path and a colour-coded, tooltipped status icon so the change type is unambiguous.
const CHANGE_META: Record<ChangeTypes, { label: string; icon: ReactNode; className: string }> = {
    new: { label: 'Added', icon: <IconPlus />, className: 'text-success' },
    deleted: { label: 'Deleted', icon: <IconMinus />, className: 'text-danger' },
    change: { label: 'Modified', icon: <IconPencil />, className: 'text-secondary' },
    'rename-pure': { label: 'Renamed', icon: <IconArrowRight />, className: 'text-secondary' },
    'rename-changed': { label: 'Renamed', icon: <IconArrowRight />, className: 'text-secondary' },
}

/** Our own file header (rendered into Pierre's light-DOM header slot): status icon + monospace path + counts. */
function FileDiffHeader({ file }: { file: FileDiffMetadata }): JSX.Element {
    const meta = CHANGE_META[file.type] ?? { label: 'Changed', icon: <IconPencil />, className: 'text-secondary' }
    let additions = 0
    let deletions = 0
    for (const hunk of file.hunks) {
        additions += hunk.additionLines
        deletions += hunk.deletionLines
    }
    const path = file.prevName ? `${file.prevName} → ${file.name}` : file.name

    return (
        <div className="flex items-center gap-2 min-w-0 border-b border-primary px-3 py-2">
            <Tooltip title={meta.label}>
                <span className={`flex shrink-0 items-center ${meta.className}`}>{meta.icon}</span>
            </Tooltip>
            <span className="truncate font-mono text-xs text-secondary" title={path}>
                {path}
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-2 font-mono text-xs tabular-nums">
                {deletions > 0 && <span className="text-danger">-{deletions}</span>}
                {additions > 0 && <span className="text-success">+{additions}</span>}
            </span>
        </div>
    )
}

/**
 * Read-only, GitHub-style rendering of a unified diff string (the branch-vs-default-branch patch the
 * backend returns for a `commit` artefact). Each file in the patch is rendered with `@pierre/diffs`,
 * which gives Shiki syntax highlighting and hunk expansion out of the box; we swap its file header for
 * our own (`renderCustomHeader`) so it reads in PostHog's visual language. Inspection only — no
 * commenting. The worker pool is disabled so highlighting runs without a separately-served worker
 * bundle; diffs are size-bounded by the backend (see `truncated`), so main-thread is fine.
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
                // rounded surface); @pierre/diffs renders the syntax-highlighted body inside.
                <div
                    key={`${file.name}-${file.cacheKey ?? file.newObjectId ?? ''}`}
                    className="overflow-hidden rounded-lg border border-primary bg-surface-primary"
                >
                    <FileDiff
                        fileDiff={file}
                        options={options}
                        renderCustomHeader={(fileDiff) => <FileDiffHeader file={fileDiff} />}
                        disableWorkerPool
                    />
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
