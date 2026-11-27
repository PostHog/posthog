import posthog from 'posthog-js'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

// pinned: error tracking tag, kept from when panels were called widgets.
export const PANEL_ERROR_TAG = 'dashboards-v2-widget'

type BoundaryProps = {
    /** A new value, such as the document after an undo or a reload, gets the content another try. */
    resetKey: unknown
    fallback: ReactNode
    /** Tells apart where the error was caught in error tracking. */
    tag: string
    children: ReactNode
}

type BoundaryState = { failed: boolean; error?: unknown; resetKey: unknown }

/**
 * Catches an error in one part of the dashboard, such as a panel, a section or the grid, so only that part shows its
 * fallback. The dashboard stays free of the app's own boundary, which needs the app's logics, so it has this small one.
 */
export class ErrorBoundary extends Component<BoundaryProps, BoundaryState> {
    override state: BoundaryState = { failed: false, resetKey: this.props.resetKey }

    static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState): BoundaryState | null {
        return props.resetKey === state.resetKey ? null : { failed: false, resetKey: props.resetKey }
    }

    static getDerivedStateFromError(error: unknown): Partial<BoundaryState> {
        return { failed: true, error }
    }

    override componentDidCatch(error: Error, info: ErrorInfo): void {
        if (isChunkLoadError(error)) {
            return
        }
        posthog.captureException(error, { tag: this.props.tag, componentStack: info.componentStack })
    }

    override render(): ReactNode {
        // A panel's failed code download goes on up to the app's chunk boundary, which reloads the page.
        if (this.state.failed && isChunkLoadError(this.state.error)) {
            throw this.state.error
        }
        return this.state.failed ? this.props.fallback : this.props.children
    }
}
