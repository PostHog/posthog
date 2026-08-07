import posthog from 'posthog-js'
import { Component, ComponentType, LazyExoticComponent, ReactNode, Suspense } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type { CodeEditorProps } from './CodeEditorImpl'

export type { CodeEditorProps } from './CodeEditorImpl'
export { clearLogicReference, initModel } from './modelLogicReference'

function makeLazyCodeEditor(): LazyExoticComponent<ComponentType<CodeEditorProps>> {
    return lazyWithRetry(() => import('./CodeEditorImpl').then((m) => ({ default: m.CodeEditor })))
}

interface State {
    error: unknown
    LazyCodeEditor: LazyExoticComponent<ComponentType<CodeEditorProps>>
}

/**
 * Lazy facade so importing CodeEditor doesn't pull monaco (~4 MB) into the importer's chunk.
 *
 * The error boundary matters as much as the laziness: without it a failed chunk fetch (a stale
 * deploy, a network blip) rethrows past a bare Suspense and renders nothing, leaving the editor
 * an empty region with no message and no way to recover.
 */
export class CodeEditor extends Component<CodeEditorProps, State> {
    override state: State = { error: null, LazyCodeEditor: makeLazyCodeEditor() }

    static getDerivedStateFromError(error: unknown): Partial<State> {
        return { error }
    }

    override componentDidCatch(error: unknown): void {
        posthog.captureException(error)
    }

    retry = (): void => {
        // React.lazy caches a rejected import, so a retry needs a fresh component to re-fetch the chunk.
        this.setState({ error: null, LazyCodeEditor: makeLazyCodeEditor() })
    }

    override render(): ReactNode {
        const { error, LazyCodeEditor } = this.state
        // CodeEditor is often sized by AutoSizer, whose wrapper is 0x0 and passes explicit width/height
        // (like monaco itself consumes). Falling back to h-full/w-full would collapse the placeholder.
        const size = { width: this.props.width ?? '100%', height: this.props.height ?? '100%' }

        if (error) {
            return (
                <div
                    className="CodeEditor flex items-center justify-center bg-surface-primary p-4"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={size}
                >
                    <LemonBanner
                        type="error"
                        className="w-full max-w-md"
                        action={{ children: 'Try again', onClick: this.retry }}
                    >
                        The code editor failed to load. This is usually a temporary network problem. Reload the page if
                        retrying doesn't help.
                    </LemonBanner>
                </div>
            )
        }

        return (
            <Suspense
                fallback={
                    <div
                        className="CodeEditor relative"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={size}
                    >
                        <Spinner />
                    </div>
                }
            >
                <LazyCodeEditor {...this.props} />
            </Suspense>
        )
    }
}
