import { useValues } from 'kea'
import type { editor } from 'monaco-editor'
import { useInView } from 'react-intersection-observer'

import { IconPencil } from '@posthog/icons'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { GenericMcpToolRenderer } from '../../sandbox/components/tool/GenericMcpToolRenderer'
import { SandboxFilePath } from '../../sandbox/components/tool/SandboxFilePath'
import { SandboxToolRow } from '../../sandbox/components/tool/SandboxToolRow'
import { ToolTitle } from '../../sandbox/components/tool/toolRowPrimitives'
import { resolveToolRowChrome } from '../../sandbox/components/tool/toolRowShared'
import type { SandboxToolRendererProps } from '../../sandbox/sandboxToolRegistry'
import { findAllDiffContent, getDiffStats, languageFromPath, type ToolCallDiffContent } from '../../toolDiffContent'

// Plan files live under the agent's plan directory; their diffs are noisy, so collapse them by default.
const PLAN_PATH_MARKER = 'claude/plans/'

// A stripped-down, unified diff that reads cleanly embedded in a chat card — mirrors the look of the
// sandbox agent's own diff UI (unified style, soft-wrapped, compact font, no editor chrome). Module-level
// so the object identity is stable across renders: MonacoDiffEditor calls `updateOptions` whenever this
// prop changes, and a fresh literal each render would thrash it during streaming.
const DIFF_EDITOR_OPTIONS: editor.IDiffEditorConstructionOptions = {
    readOnly: true,
    renderSideBySide: false,
    hideUnchangedRegions: { enabled: true },
    diffAlgorithm: 'advanced',
    wordWrap: 'on',
    diffWordWrap: 'inherit',
    fontSize: 12,
    lineNumbers: 'on',
    minimap: { enabled: false },
    renderOverviewRuler: false,
    overviewRulerLanes: 0,
    overviewRulerBorder: false,
    hideCursorInOverviewRuler: true,
    scrollBeyondLastLine: false,
    folding: false,
    glyphMargin: false,
    renderLineHighlight: 'none',
    renderGutterMenu: false,
    guides: { indentation: false },
    padding: { top: 4, bottom: 4 },
    // Don't trap the thread's scroll when the cursor is over the diff.
    scrollbar: { alwaysConsumeMouseWheel: false, vertical: 'auto', horizontal: 'auto' },
}

function DiffEditor({ diff, path }: { diff: ToolCallDiffContent; path?: string }): JSX.Element {
    // Lazy-mount: only instantiate the Monaco diff editor once the card scrolls near the viewport. This
    // bounds the number of live editors to what's on screen.
    const { ref, inView } = useInView({ rootMargin: '500px', triggerOnce: true })
    // Match the surrounding app theme — without this Monaco falls back to its default `vs` (white) theme,
    // which looks broken on a dark card. Same wiring CodeEditorImpl uses.
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <div ref={ref} className="w-full min-w-0">
            {inView ? (
                <MonacoDiffEditor
                    original={diff.oldText ?? ''}
                    value={diff.newText ?? ''}
                    modified={diff.newText ?? ''}
                    language={languageFromPath(path)}
                    theme={isDarkModeOn ? 'vs-dark' : 'vs'}
                    options={DIFF_EDITOR_OPTIONS}
                />
            ) : (
                <div className="h-24 rounded border border-border-secondary" />
            )}
        </div>
    )
}

/** +added / -removed mono stat chip for a diff (or aggregate). */
function DiffStats({ added, removed }: { added: number; removed: number }): JSX.Element {
    return (
        <span className="font-mono text-[13px] shrink-0">
            <span className="text-success">+{added}</span> <span className="text-danger">-{removed}</span>
        </span>
    )
}

/**
 * Renderer for Edit / Write / MultiEdit / NotebookEdit. When the agent attached `type: "diff"` content
 * blocks (full-file old/new text) it shows the file path + line stats in the header and an inline visual
 * diff in the body; MultiEdit lists one diff per edit. Without diff blocks it degrades to the generic
 * card, so non-diff edits and not-yet-streamed content still render.
 */
export function EditDiffRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon } = props
    const diffs = findAllDiffContent(message.content)

    if (diffs.length === 0) {
        return <GenericMcpToolRenderer {...props} />
    }

    const chrome = resolveToolRowChrome(props)
    const fallbackPath = typeof message.rawInput.file_path === 'string' ? message.rawInput.file_path : undefined
    const primaryPath = diffs[0].path ?? fallbackPath
    const isSingle = diffs.length === 1

    const total = diffs.reduce(
        (acc, diff) => {
            const stats = getDiffStats(diff.oldText, diff.newText)
            return { added: acc.added + stats.added, removed: acc.removed + stats.removed }
        },
        { added: 0, removed: 0 }
    )

    const header =
        isSingle && primaryPath ? (
            <>
                <SandboxFilePath path={primaryPath} />
                <DiffStats {...total} />
            </>
        ) : (
            <>
                <ToolTitle>{message.title || `Edit ${diffs.length} files`}</ToolTitle>
                <DiffStats {...total} />
            </>
        )

    const content = (
        <div className="flex flex-col gap-3 w-full min-w-0">
            {diffs.map((diff, index) => {
                const path = diff.path ?? fallbackPath
                return (
                    <div key={index} className="flex flex-col gap-1 w-full min-w-0">
                        {!isSingle && path && <SandboxFilePath path={path} />}
                        <DiffEditor diff={diff} path={path} />
                    </div>
                )
            })}
        </div>
    )

    return (
        <SandboxToolRow
            icon={icon ?? <IconPencil />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            defaultOpen={!(primaryPath ?? '').includes(PLAN_PATH_MARKER)}
            content={content}
            debugDetails={chrome.debugDetails}
        >
            {header}
        </SandboxToolRow>
    )
}
