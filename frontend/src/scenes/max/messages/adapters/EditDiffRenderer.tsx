import { useValues } from 'kea'
import type { editor } from 'monaco-editor'
import { useInView } from 'react-intersection-observer'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { SandboxToolActivity } from '../../components/Activity'
import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { findAllDiffContent, getDiffStats, languageFromPath, type ToolCallDiffContent } from '../../toolDiffContent'

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

function EditDiffBody({ diff, fallbackPath }: { diff: ToolCallDiffContent; fallbackPath?: string }): JSX.Element {
    // Lazy-mount: render the cheap stat line always, but only instantiate the Monaco diff editor once
    // the card scrolls near the viewport. This bounds the number of live editors to what's on screen.
    const { ref, inView } = useInView({ rootMargin: '500px', triggerOnce: true })
    // Match the surrounding app theme — without this Monaco falls back to its default `vs` (white) theme,
    // which looks broken on a dark card. Same wiring CodeEditorImpl uses.
    const { isDarkModeOn } = useValues(themeLogic)
    const path = diff.path ?? fallbackPath
    const { added, removed } = getDiffStats(diff.oldText, diff.newText)

    return (
        <div ref={ref} className="flex flex-col gap-1 w-full min-w-0">
            <div className="flex items-center gap-2 min-w-0">
                {path && <span className="font-mono text-xs text-muted truncate">{path}</span>}
                <span className="font-mono text-xs shrink-0">
                    <span className="text-success">+{added}</span> <span className="text-danger">-{removed}</span>
                </span>
            </div>
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

/**
 * Renderer for Edit/Write/MultiEdit/NotebookEdit tool calls. When the agent attached `type: "diff"`
 * content blocks (full-file old/new text), it shows an inline visual diff with +/- line stats inside
 * the standard tool card. Otherwise it degrades to the plain `SandboxToolActivity` card — this
 * renderer is a strict superset of `FallbackMcpToolRenderer`, so non-diff edits and not-yet-streamed
 * content render exactly as before.
 */
export function EditDiffRenderer(props: McpToolRendererProps): JSX.Element {
    const { message, icon, displayName } = props
    const diffs = findAllDiffContent(message.content)

    if (diffs.length === 0) {
        return <SandboxToolActivity message={message} icon={icon} displayName={displayName} />
    }

    const fallbackPath = typeof message.rawInput.file_path === 'string' ? message.rawInput.file_path : undefined

    return (
        <SandboxToolActivity message={message} icon={icon} displayName={displayName}>
            <div className="flex flex-col gap-3 w-full min-w-0">
                {diffs.map((diff, index) => (
                    <EditDiffBody key={index} diff={diff} fallbackPath={fallbackPath} />
                ))}
            </div>
        </SandboxToolActivity>
    )
}
