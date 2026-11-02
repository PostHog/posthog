import clsx from 'clsx'
import posthog from 'posthog-js'
import { Component, ComponentType, LazyExoticComponent, ReactNode, Suspense } from 'react'

import type { TextContentProps } from 'lib/components/Cards/TextCard/TextContent'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LazyLemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LazyLemonMarkdown'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { lazyWithRetry, retryImport } from 'lib/utils/retryImport'
import { reloadAfterChunkLoadError } from 'lib/utils/stableChunks'

import type { LemonRichContentEditorProps } from './LemonRichContentEditor'
import { richContentToText } from './richContentText'
import type { JSONContent } from './types'

const importTextContent = (): Promise<typeof import('lib/components/Cards/TextCard/TextContent')> =>
    import('lib/components/Cards/TextCard/TextContent')
const importLemonRichContentEditor = (): Promise<typeof import('./LemonRichContentEditor')> =>
    import('./LemonRichContentEditor')

interface RetryableChunk<T extends ComponentType<any>> {
    get: () => LazyExoticComponent<T>
    reset: () => void
}

// React.lazy keeps a failed import forever, so a retry needs a new lazy component.
function retryableChunk<T extends ComponentType<any>>(factory: () => Promise<{ default: T }>): RetryableChunk<T> {
    let chunk = lazyWithRetry(factory)
    return {
        get: () => chunk,
        reset: () => {
            chunk = lazyWithRetry(factory)
        },
    }
}

const textContentChunk = retryableChunk(() => importTextContent().then((m) => ({ default: m.TextContent })))
const richContentPreviewChunk = retryableChunk(() =>
    importLemonRichContentEditor().then((m) => ({ default: m.RichContentPreview }))
)
const lemonRichContentEditorChunk = retryableChunk(() =>
    importLemonRichContentEditor().then((m) => ({ default: m.LemonRichContentEditor }))
)

interface LazyChunkProps<P extends object> {
    chunk: RetryableChunk<ComponentType<P>>
    chunkProps: P
    loading: ReactNode
    renderError: (recover: ChunkRecovery) => ReactNode
}

interface ChunkRecovery {
    label: string
    onClick: () => void
}

/**
 * Keeps a failed rich text chunk local to the component that needs it. Without it the error reaches the
 * app's ChunkLoadErrorBoundary, which reloads the page and drops what the user was doing.
 */
class LazyChunk<P extends object> extends Component<LazyChunkProps<P>, { error: unknown; retried: boolean }> {
    override state: { error: unknown; retried: boolean } = { error: null, retried: false }

    static getDerivedStateFromError(error: unknown): { error: unknown } {
        return { error }
    }

    override componentDidCatch(error: unknown): void {
        if (isChunkLoadError(error)) {
            posthog.captureException(error)
        }
    }

    retry = (): void => {
        this.props.chunk.reset()
        this.setState({ error: null, retried: true })
    }

    // The browser caches a chunk that fails to parse, and a deploy deletes old chunks, so a second
    // failure or a parse failure needs a reload. The user chooses it, so no unsaved work is lost by surprise.
    recovery(error: unknown): ChunkRecovery {
        const needsReload = this.state.retried || (error as { name?: string }).name === 'SyntaxError'
        return needsReload
            ? { label: 'Reload page', onClick: () => reloadAfterChunkLoadError(error) }
            : { label: 'Try again', onClick: this.retry }
    }

    override render(): ReactNode {
        const { error } = this.state
        if (error && !isChunkLoadError(error)) {
            throw error
        }
        if (error) {
            return this.props.renderError(this.recovery(error))
        }
        // Read on every render, so a retry renders the new lazy component.
        const Chunk: ComponentType<P> = this.props.chunk.get()
        return (
            <Suspense fallback={this.props.loading}>
                <Chunk {...this.props.chunkProps} />
            </Suspense>
        )
    }
}

/**
 * Starts loading the rich text stack before a component needs it. Call it from a logic as soon as
 * its data shows that rich text will render, so the chunk loads while the rest of the scene renders.
 */
export function preloadRichContent(): void {
    void Promise.all([retryImport(importTextContent), retryImport(importLemonRichContentEditor)]).catch(() => {
        // The lazy component retries the import when it renders, and its error boundary handles a failure.
    })
}

function PlainTextContent({ text, className, busy }: TextContentProps & { busy?: boolean }): JSX.Element {
    return (
        <div className={clsx('w-full', className)} aria-busy={busy}>
            <LazyLemonMarkdown className="overflow-auto">{text}</LazyLemonMarkdown>
        </div>
    )
}

/** `TextContent` loaded on first render. The text renders as plain markdown while the chunk loads, or if it fails. */
export function LazyTextContent(props: TextContentProps): JSX.Element {
    return (
        <LazyChunk
            chunk={textContentChunk}
            chunkProps={props}
            loading={<PlainTextContent {...props} busy />}
            renderError={() => <PlainTextContent {...props} />}
        />
    )
}

function PlainRichContentPreview({
    content,
    className,
    busy,
}: {
    content: JSONContent | null
    className?: string
    busy?: boolean
}): JSX.Element {
    return (
        <div
            className={clsx('w-full p-2 whitespace-pre-line [overflow-wrap:anywhere]', busy && 'invisible', className)}
            aria-busy={busy}
        >
            {content ? richContentToText(content, (id) => `@member:${id}`) : null}
        </div>
    )
}

/** `RichContentPreview` loaded on first render. The plain text holds the height while the chunk loads, and shows if it fails. */
export function LazyRichContentPreview(props: { content: JSONContent | null; className?: string }): JSX.Element {
    return (
        <LazyChunk
            chunk={richContentPreviewChunk}
            chunkProps={props}
            loading={<PlainRichContentPreview {...props} busy />}
            renderError={() => <PlainRichContentPreview {...props} />}
        />
    )
}

/** `LemonRichContentEditor` loaded on first render. An empty input holds its place while the chunk loads. */
export function LazyLemonRichContentEditor(props: LemonRichContentEditorProps): JSX.Element {
    return (
        <LazyChunk
            chunk={lemonRichContentEditorChunk}
            chunkProps={props}
            loading={
                <div className="flex flex-col border rounded mt-4 input-like" aria-busy>
                    <div className="p-2 min-h-16" />
                    <div className="h-8 border-t" />
                </div>
            }
            renderError={(recover) => (
                <div className="flex flex-col border rounded mt-4 input-like">
                    <div className="p-2 min-h-16 text-secondary">Couldn't load the editor.</div>
                    <div className="flex justify-end border-t p-1">
                        <LemonButton size="xsmall" type="secondary" onClick={recover.onClick}>
                            {recover.label}
                        </LemonButton>
                    </div>
                </div>
            )}
        />
    )
}
