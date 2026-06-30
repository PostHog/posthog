import 'react-diff-view/style/index.css'
import './PullRequestDiffView.scss'

import { useMemo, useState } from 'react'
import { Decoration, Diff, type FileData, Hunk, parseDiff } from 'react-diff-view'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'

/** Added/removed line counts for a parsed file — feeds the GitHub-style "+N −M" header badge. */
function countChanges(file: FileData): { additions: number; deletions: number } {
    let additions = 0
    let deletions = 0
    for (const hunk of file.hunks) {
        for (const change of hunk.changes) {
            if (change.type === 'insert') {
                additions++
            } else if (change.type === 'delete') {
                deletions++
            }
        }
    }
    return { additions, deletions }
}

/** Path label for a file row: a rename/copy reads `old → new`, a delete its old path, else the new path. */
function filePathLabel(file: FileData): string {
    if (file.type === 'rename' || file.type === 'copy') {
        return `${file.oldPath} → ${file.newPath}`
    }
    if (file.type === 'delete') {
        return file.oldPath
    }
    return file.newPath || file.oldPath
}

/**
 * One file's diff, GitHub-style: a collapsible header (path + add/remove counts) over a unified
 * hunk view. Binary and empty files surface a clean note instead of an empty table.
 */
function DiffFile({ file }: { file: FileData }): JSX.Element {
    const [collapsed, setCollapsed] = useState(false)
    const { additions, deletions } = countChanges(file)

    return (
        <div className="rounded border border-primary bg-surface-primary overflow-hidden">
            <button
                type="button"
                onClick={() => setCollapsed((c) => !c)}
                aria-expanded={!collapsed}
                className="flex w-full items-center gap-2 px-3 py-2 text-left bg-surface-secondary border-b border-primary transition-colors hover:bg-fill-highlight-50"
            >
                {collapsed ? (
                    <IconChevronRight className="size-3 shrink-0 text-tertiary" />
                ) : (
                    <IconChevronDown className="size-3 shrink-0 text-tertiary" />
                )}
                <span className="font-mono text-[12px] text-primary truncate">{filePathLabel(file)}</span>
                <span className="ml-auto flex shrink-0 items-center gap-2 text-[11px] tabular-nums font-mono">
                    {additions > 0 && <span className="text-success">+{additions}</span>}
                    {deletions > 0 && <span className="text-danger">−{deletions}</span>}
                </span>
            </button>
            {!collapsed ? (
                file.isBinary ? (
                    <p className="m-0 px-3 py-2 text-[12px] text-tertiary italic">Binary file not shown.</p>
                ) : file.hunks.length === 0 ? (
                    <p className="m-0 px-3 py-2 text-[12px] text-tertiary italic">No textual changes.</p>
                ) : (
                    <Diff viewType="unified" diffType={file.type} hunks={file.hunks} className="ph-diff">
                        {(hunks) =>
                            hunks.flatMap((hunk, i) => [
                                <Decoration key={`decoration-${i}`} className="ph-diff-hunk-header">
                                    <span className="block px-3 py-1 font-mono text-[11px] text-tertiary">
                                        {hunk.content}
                                    </span>
                                </Decoration>,
                                <Hunk key={`hunk-${i}`} hunk={hunk} />,
                            ])
                        }
                    </Diff>
                )
            ) : null}
        </div>
    )
}

/**
 * Read-only, GitHub-style rendering of a unified diff string (the branch-vs-default-branch patch the
 * backend returns for a `commit` artefact). Parses the patch into files and renders each as a
 * collapsible unified hunk view. No commenting — inspection only.
 */
export function PullRequestDiffView({ diff, truncated }: { diff: string; truncated: boolean }): JSX.Element {
    const files = useMemo(() => {
        if (!diff.trim()) {
            return []
        }
        try {
            return parseDiff(diff)
        } catch {
            return []
        }
    }, [diff])

    if (files.length === 0) {
        return <p className="m-0 text-sm text-tertiary">No file changes to display for this branch.</p>
    }

    return (
        <div className="flex flex-col gap-3">
            {files.map((file, i) => (
                <DiffFile key={`${file.oldRevision}-${file.newPath || file.oldPath || i}`} file={file} />
            ))}
            {truncated ? (
                <p className="m-0 text-[12px] text-tertiary italic">
                    Diff truncated — open the pull request in GitHub for the full change.
                </p>
            ) : null}
        </div>
    )
}
