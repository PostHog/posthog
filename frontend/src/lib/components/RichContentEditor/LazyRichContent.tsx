import clsx from 'clsx'
import { Suspense } from 'react'

import type { TextContentProps } from 'lib/components/Cards/TextCard/TextContent'
import { LazyLemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LazyLemonMarkdown'
import { lazyWithRetry, retryImport } from 'lib/utils/retryImport'

import type { LemonRichContentEditorProps } from './LemonRichContentEditor'
import { richContentToText } from './richContentText'
import type { JSONContent } from './types'

const importTextContent = (): Promise<typeof import('lib/components/Cards/TextCard/TextContent')> =>
    import('lib/components/Cards/TextCard/TextContent')
const importLemonRichContentEditor = (): Promise<typeof import('./LemonRichContentEditor')> =>
    import('./LemonRichContentEditor')

const TextContentChunk = lazyWithRetry(() => importTextContent().then((m) => ({ default: m.TextContent })))
const RichContentPreviewChunk = lazyWithRetry(() =>
    importLemonRichContentEditor().then((m) => ({ default: m.RichContentPreview }))
)
const LemonRichContentEditorChunk = lazyWithRetry(() =>
    importLemonRichContentEditor().then((m) => ({ default: m.LemonRichContentEditor }))
)

/**
 * Starts loading the rich text stack before a component needs it. Call it from a logic as soon as
 * its data shows that rich text will render, so the chunk loads while the rest of the scene renders.
 */
export function preloadRichContent(): void {
    void Promise.all([retryImport(importTextContent), retryImport(importLemonRichContentEditor)]).catch(() => {
        // The lazy component retries the import when it renders, and its error boundary reports a failure.
    })
}

/** `TextContent` loaded on first render. While the chunk loads, the text renders as plain markdown. */
export function LazyTextContent(props: TextContentProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div className={clsx('w-full', props.className)} aria-busy>
                    <LazyLemonMarkdown className="overflow-auto">{props.text}</LazyLemonMarkdown>
                </div>
            }
        >
            <TextContentChunk {...props} />
        </Suspense>
    )
}

/** `RichContentPreview` loaded on first render. While the chunk loads, the plain text holds the height. */
export function LazyRichContentPreview(props: { content: JSONContent | null; className?: string }): JSX.Element {
    return (
        <Suspense
            fallback={
                <div
                    className={clsx(
                        'w-full p-2 invisible whitespace-pre-line [overflow-wrap:anywhere]',
                        props.className
                    )}
                    aria-busy
                >
                    {props.content ? richContentToText(props.content, (id) => `@member:${id}`) : null}
                </div>
            }
        >
            <RichContentPreviewChunk {...props} />
        </Suspense>
    )
}

/** `LemonRichContentEditor` loaded on first render. While the chunk loads, an empty input holds its place. */
export function LazyLemonRichContentEditor(props: LemonRichContentEditorProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div className="flex flex-col border rounded mt-4 input-like" aria-busy>
                    <div className="p-2 min-h-16" />
                    <div className="h-8 border-t" />
                </div>
            }
        >
            <LemonRichContentEditorChunk {...props} />
        </Suspense>
    )
}
