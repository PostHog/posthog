import posthog from 'posthog-js'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

import type { SavedWidget } from '../dashboard/document/dashboardTypes'

type WidgetErrorState = {
    failed: boolean
    error?: unknown
    widget: SavedWidget
}

/**
 * Catches an error in one part of one widget, so the tile around it can still be moved, resized and removed.
 * The dashboard stays free of the app's own boundary, which needs the app's logics, so it has this small one.
 */
export class WidgetErrorBoundary extends Component<
    { widget: SavedWidget; fallback: ReactNode; children: ReactNode },
    WidgetErrorState
> {
    override state: WidgetErrorState = { failed: false, widget: this.props.widget }

    // A changed widget, such as a new chart type picked from the tile menu, gets another try.
    static getDerivedStateFromProps(props: { widget: SavedWidget }, state: WidgetErrorState): WidgetErrorState | null {
        return props.widget === state.widget ? null : { failed: false, widget: props.widget }
    }

    static getDerivedStateFromError(error: unknown): Partial<WidgetErrorState> {
        return { failed: true, error }
    }

    override componentDidCatch(error: Error, info: ErrorInfo): void {
        if (isChunkLoadError(error)) {
            return
        }
        posthog.captureException(error, { tag: 'dashboards-v2-widget', componentStack: info.componentStack })
    }

    override render(): ReactNode {
        const { failed, error } = this.state
        // A widget whose code failed to download after a deploy needs the page reloaded, which the app's chunk
        // boundary does, so the error goes on up to it. React caches the failed import, so a retry here can't help.
        if (failed && isChunkLoadError(error)) {
            throw error
        }
        return failed ? this.props.fallback : this.props.children
    }
}
