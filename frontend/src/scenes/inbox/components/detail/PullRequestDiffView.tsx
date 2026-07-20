import { type ChangeTypes, type FileDiffMetadata, type FileDiffOptions, parsePatchFiles } from '@pierre/diffs'
import { FileDiff } from '@pierre/diffs/react'
import { useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { IconArrowRight, IconMinus, IconPencil, IconPlus } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

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

// Rough per-row / header heights (px) of Pierre's rendered diff, used only to size the loading
// placeholder so the card doesn't collapse to a bare header while highlighting runs.
const DIFF_ROW_HEIGHT = 20
const DIFF_HEADER_HEIGHT = 37

export interface DiffSummary {
    fileCount: number
    additions: number
    deletions: number
}

/** Estimate how many rows a file's diff renders, to size its loading placeholder. Capped so a huge
 * file doesn't reserve a screen-height of skeleton. */
function estimateDiffRows(file: FileDiffMetadata): number {
    let rows = 0
    for (const hunk of file.hunks) {
        // Added + deleted changed lines, plus a little context around each hunk.
        rows += hunk.additionLines + hunk.deletionLines + 3
    }
    return Math.max(3, Math.min(rows, 18))
}

const SKELETON_LINE_WIDTHS = ['w-3/4', 'w-1/2', 'w-5/6', 'w-2/3', 'w-4/5', 'w-1/3', 'w-3/5', 'w-11/12']

/** Code-shaped placeholder (header bar + gutter + line rows) shown over a file's card until Pierre
 * finishes highlighting its body — otherwise the body is empty and files read as stacked header rules. */
function DiffFileCardSkeleton({ rows }: { rows: number }): JSX.Element {
    return (
        <div className="animate-pulse" aria-hidden>
            <div
                className="flex items-center gap-2 border-b border-primary px-3"
                style={{ height: DIFF_HEADER_HEIGHT }}
            >
                <div className="size-3.5 shrink-0 rounded bg-fill-highlight-100" />
                <div className="h-2.5 w-40 rounded bg-fill-highlight-100" />
            </div>
            <div className="flex flex-col py-1">
                {Array.from({ length: rows }).map((_, i) => (
                    <div key={i} className="flex items-center gap-3 px-3" style={{ height: DIFF_ROW_HEIGHT }}>
                        <div className="h-2.5 w-6 shrink-0 rounded bg-fill-highlight-50" />
                        <div
                            className={`h-2.5 rounded bg-fill-highlight-50 ${SKELETON_LINE_WIDTHS[i % SKELETON_LINE_WIDTHS.length]}`}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}

/**
 * Card chrome around one file's `FileDiff`. `@pierre/diffs` highlights the body asynchronously (Shiki),
 * so on first paint the body is empty and the file is just its header. This reserves an estimated height
 * and overlays a skeleton until the real body renders — detected by the wrapper growing past its header
 * (with a timeout fallback for degenerate zero-line files that never grow).
 */
function DiffFileCard({ file, children }: { file: FileDiffMetadata; children: ReactNode }): JSX.Element {
    const [rendered, setRendered] = useState(false)
    const bodyRef = useRef<HTMLDivElement>(null)
    const rows = useMemo(() => estimateDiffRows(file), [file])

    useEffect(() => {
        const el = bodyRef.current
        if (!el) {
            return
        }
        let done = false
        const finish = (): void => {
            if (!done) {
                done = true
                setRendered(true)
            }
        }
        const observer = new ResizeObserver(() => {
            if (el.offsetHeight > DIFF_HEADER_HEIGHT + DIFF_ROW_HEIGHT) {
                finish()
            }
        })
        observer.observe(el)
        const timer = setTimeout(finish, 2500)
        return () => {
            observer.disconnect()
            clearTimeout(timer)
        }
    }, [])

    return (
        <div
            className="relative overflow-hidden rounded-lg border border-primary bg-surface-primary"
            style={rendered ? undefined : { minHeight: DIFF_HEADER_HEIGHT + rows * DIFF_ROW_HEIGHT }}
        >
            <div ref={bodyRef}>{children}</div>
            {!rendered && (
                <div className="absolute inset-0 bg-surface-primary">
                    <DiffFileCardSkeleton rows={rows} />
                </div>
            )}
        </div>
    )
}

/** Aggregate file/line counts from a unified diff patch — shared by the diff toolbar and file headers. */
export function summarizeDiff(diff: string, cacheKey?: string): DiffSummary | null {
    if (!diff.trim()) {
        return { fileCount: 0, additions: 0, deletions: 0 }
    }
    try {
        const files = parsePatchFiles(diff, cacheKey).flatMap((patch) => patch.files)
        let additions = 0
        let deletions = 0
        for (const file of files) {
            for (const hunk of file.hunks) {
                additions += hunk.additionLines
                deletions += hunk.deletionLines
            }
        }
        return { fileCount: files.length, additions, deletions }
    } catch {
        return null
    }
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

    const optionsByFile = useMemo<Map<string, FileDiffOptions<never>>>(() => {
        const map = new Map<string, FileDiffOptions<never>>()
        for (const file of files) {
            map.set(file.name, {
                theme: DIFF_THEME,
                themeType: isDarkModeOn ? 'dark' : 'light',
                diffStyle,
                stickyHeader: true,
                overflow: 'scroll',
            })
        }
        return map
    }, [files, isDarkModeOn, diffStyle])

    if (parseFailed) {
        return <p className="m-0 text-sm text-danger">Couldn't parse this diff — it may be in an unexpected format.</p>
    }

    if (files.length === 0) {
        return <p className="m-0 text-sm text-tertiary">No file changes to display for this branch.</p>
    }

    return (
        <div className="flex flex-col gap-3">
            {files.map((file) => (
                // Card chrome (bordered, rounded surface) so the diff sits in PostHog's visual language;
                // @pierre/diffs renders the syntax-highlighted body inside, with a skeleton until it does.
                <DiffFileCard key={`${file.name}-${file.cacheKey ?? file.newObjectId ?? ''}`} file={file}>
                    <FileDiff
                        fileDiff={file}
                        options={optionsByFile.get(file.name)}
                        renderCustomHeader={(fileDiff) => <FileDiffHeader file={fileDiff} />}
                        disableWorkerPool
                    />
                </DiffFileCard>
            ))}
            {truncated ? (
                <p className="m-0 text-xs text-tertiary italic">
                    Diff truncated — open the pull request in GitHub for the full change.
                </p>
            ) : null}
        </div>
    )
}
