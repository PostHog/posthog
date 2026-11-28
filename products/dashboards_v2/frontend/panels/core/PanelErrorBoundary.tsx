import posthog from 'posthog-js'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

import { type SavedPanel } from './panelSchema'

type PanelErrorState = {
    failed: boolean
    error?: unknown
    panel: SavedPanel
}

/**
 * Catches an error in one part of one panel, so the tile around it can still be moved, resized and removed.
 * The dashboard stays free of the app's own boundary, which needs the app's logics, so it has this small one.
 */
export class PanelErrorBoundary extends Component<
    { panel: SavedPanel; fallback: ReactNode; children: ReactNode },
    PanelErrorState
> {
    override state: PanelErrorState = { failed: false, panel: this.props.panel }

    // A changed panel, such as a new chart type picked from the tile menu, gets another try.
    static getDerivedStateFromProps(props: { panel: SavedPanel }, state: PanelErrorState): PanelErrorState | null {
        return props.panel === state.panel ? null : { failed: false, panel: props.panel }
    }

    static getDerivedStateFromError(error: unknown): Partial<PanelErrorState> {
        return { failed: true, error }
    }

    override componentDidCatch(error: Error, info: ErrorInfo): void {
        if (isChunkLoadError(error)) {
            return
        }
        // pinned: error tracking tag, kept from when panels were called widgets.
        posthog.captureException(error, { tag: 'dashboards-v2-widget', componentStack: info.componentStack })
    }

    override render(): ReactNode {
        const { failed, error } = this.state
        // A panel whose code failed to download after a deploy needs the page reloaded, which the app's chunk
        // boundary does, so the error goes on up to it. React caches the failed import, so a retry here can't help.
        if (failed && isChunkLoadError(error)) {
            throw error
        }
        return failed ? this.props.fallback : this.props.children
    }
}
