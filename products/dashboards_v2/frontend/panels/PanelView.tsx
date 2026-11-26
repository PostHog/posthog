import posthog from 'posthog-js'
import { Component, type ComponentType, type ErrorInfo, type ReactNode, Suspense, memo } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

import type { ContentPanel } from '../dashboard/dashboardTypes'
import type { PanelComponentProps, PanelDefinition } from './panelDefinition'
import { PanelLoading } from './PanelLoading'

interface TileErrorState {
    failed: boolean
    error?: unknown
    panel: ContentPanel
}

// The dashboard stays free of the app's own boundary, which needs the app's logics, so it has this small one.
class TileErrorBoundary extends Component<{ panel: ContentPanel; children: ReactNode }, TileErrorState> {
    override state: TileErrorState = { failed: false, panel: this.props.panel }

    // A changed panel, such as a new chart type picked from the tile menu, gets another try.
    static getDerivedStateFromProps(props: { panel: ContentPanel }, state: TileErrorState): TileErrorState | null {
        return props.panel === state.panel ? null : { failed: false, panel: props.panel }
    }

    static getDerivedStateFromError(error: unknown): Partial<TileErrorState> {
        return { failed: true, error }
    }

    override componentDidCatch(error: Error, info: ErrorInfo): void {
        if (isChunkLoadError(error)) {
            return
        }
        // The tag predates the panel rename; saved exception filters match on it, so it stays.
        posthog.captureException(error, { tag: 'dashboards-v2-widget', componentStack: info.componentStack })
    }

    override render(): ReactNode {
        const { failed, error } = this.state
        // A panel whose code failed to download after a deploy needs the page reloaded, which the app's chunk
        // boundary does, so the error goes on up to it. React caches the failed import, so a retry here can't help.
        if (failed && isChunkLoadError(error)) {
            throw error
        }
        if (failed) {
            return (
                <div className="flex h-full items-center justify-center text-secondary text-sm">
                    This panel hit an error.
                </div>
            )
        }
        return this.props.children
    }
}

/**
 * Memoised on the panel, its definition and `setConfig`, which all keep their identity through every layout edit, so
 * moving tiles never re-renders it.
 */
export const PanelView = memo(function PanelView({
    panel,
    definition,
    setConfig,
}: PanelComponentProps & {
    definition: PanelDefinition | undefined
}): JSX.Element {
    if (!definition) {
        return (
            <div className="flex h-full items-center justify-center text-secondary text-sm">
                This dashboard can't show this panel type.
            </div>
        )
    }
    const Loading: ComponentType<{ panel: ContentPanel }> = definition.Loading ?? PanelLoading
    // One panel that throws or suspends shows its own state, and the rest of the dashboard keeps working.
    return (
        <TileErrorBoundary panel={panel}>
            <Suspense fallback={<Loading panel={panel} />}>
                <definition.Component panel={panel} setConfig={setConfig} />
            </Suspense>
        </TileErrorBoundary>
    )
})
