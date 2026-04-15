import { useEffect, useState } from 'react'

import { toolbarLogger } from '~/toolbar/toolbarLogger'

/**
 * Renders assistant markdown inside the toolbar chat.
 *
 * We deliberately *don't* reuse `scenes/max/MarkdownMessage` because its
 * dependency chain (LemonMarkdown → CodeSnippet → highlight.js → RichContentMention
 * via TipTap → kea) pulls in hundreds of KB and has caused circular/TDZ
 * evaluation issues when loaded from the toolbar bundle on customer sites.
 *
 * Instead we pull `react-markdown` + `remark-gfm` via a code-split chunk so the
 * base toolbar bundle stays lean. Until the chunk resolves we fall back to
 * plain text — no flash-to-spinner — and if the chunk fails to load we stay on
 * plain text rather than breaking the chat.
 */
type ReactMarkdownModule = typeof import('react-markdown')
type RemarkGfmModule = typeof import('remark-gfm')

type MarkdownModules = {
    ReactMarkdown: ReactMarkdownModule['default']
    remarkGfm: RemarkGfmModule['default']
}

let modulesPromise: Promise<MarkdownModules> | null = null

function loadMarkdownModules(): Promise<MarkdownModules> {
    if (!modulesPromise) {
        modulesPromise = Promise.all([import('react-markdown'), import('remark-gfm')])
            .then(([reactMarkdown, remarkGfm]) => ({
                ReactMarkdown: reactMarkdown.default,
                remarkGfm: remarkGfm.default,
            }))
            .catch((err) => {
                modulesPromise = null
                toolbarLogger.warn('ai', 'Markdown renderer failed to load; falling back to plain text', {
                    message: err instanceof Error ? err.message : String(err),
                })
                throw err
            })
    }
    return modulesPromise
}

/** Kick off the markdown-chunk download ahead of the first render. */
export function preloadMarkdown(): void {
    void loadMarkdownModules().catch(() => {
        // swallowed — load errors are already logged inside loadMarkdownModules
    })
}

export function ToolbarMarkdown({ content }: { content: string; id: string }): JSX.Element {
    const [modules, setModules] = useState<MarkdownModules | null>(null)

    useEffect(() => {
        let cancelled = false
        loadMarkdownModules()
            .then((loaded) => {
                if (!cancelled) {
                    setModules(loaded)
                }
            })
            .catch(() => {
                // swallowed — stay on plain-text fallback
            })
        return () => {
            cancelled = true
        }
    }, [])

    if (!modules) {
        return <>{content}</>
    }
    const { ReactMarkdown, remarkGfm } = modules
    return (
        <div className="ToolbarAIMenu__markdown">
            {/* oxlint-disable-next-line react/forbid-elements -- we deliberately avoid
                LemonMarkdown here because its transitive deps (CodeSnippet → highlight.js,
                RichContentMention → TipTap, kea) bloat the toolbar bundle that ships to
                every customer site. See ToolbarMarkdown module comment for details. */}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
    )
}
