/**
 * Markdown renderer for assistant text. Thin wrapper around
 * `react-markdown` + `remark-gfm` (tables / strikethrough / task lists),
 * scoped to the small set of elements that show up in agent replies.
 *
 * Streaming-aware: `react-markdown` re-parses on every render, so it
 * handles partial markdown gracefully — half-finished code fences or
 * lists render as their best-effort interpretation until the next
 * delta closes them out.
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownProps {
    children: string
}

export function Markdown({ children }: MarkdownProps): React.ReactElement {
    return (
        <div className="space-y-2 text-sm leading-relaxed [&_a]:underline [&_a]:underline-offset-2 [&_code]:rounded [&_code]:bg-muted/50 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.8125rem] [&_code]:font-mono [&_h1]:mt-3 [&_h1]:text-base [&_h1]:font-semibold [&_h2]:mt-3 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:mt-2 [&_h3]:text-sm [&_h3]:font-medium [&_hr]:my-2 [&_hr]:border-border [&_li]:my-0.5 [&_ol]:ml-5 [&_ol]:list-decimal [&_p]:my-0 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted/60 [&_pre]:p-2 [&_pre>code]:bg-transparent [&_pre>code]:p-0 [&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:bg-muted/40 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_ul]:ml-5 [&_ul]:list-disc">
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                    // Open links in a new tab — the dock is embedded; we
                    // don't want a click in the chat to navigate the
                    // host page out from under the user.
                    a: ({ href, children }) => (
                        <a href={href} target="_blank" rel="noreferrer noopener">
                            {children}
                        </a>
                    ),
                }}
            >
                {children}
            </ReactMarkdown>
        </div>
    )
}
