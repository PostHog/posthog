import posthog from 'posthog-js'
import { Component, type ComponentType, type ErrorInfo, type ReactNode, Suspense, memo } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

import type { ContentWidget } from '../dashboard/dashboardTypes'
import type { WidgetComponentProps, WidgetDefinition } from './widgetDefinition'
import { WidgetLoading } from './WidgetLoading'

interface TileErrorState {
    failed: boolean
    error?: unknown
    widget: ContentWidget
}

// The dashboard stays free of the app's own boundary, which needs the app's logics, so it has this small one.
class TileErrorBoundary extends Component<{ widget: ContentWidget; children: ReactNode }, TileErrorState> {
    override state: TileErrorState = { failed: false, widget: this.props.widget }

    // A changed widget, such as a new chart type picked from the tile menu, gets another try.
    static getDerivedStateFromProps(props: { widget: ContentWidget }, state: TileErrorState): TileErrorState | null {
        return props.widget === state.widget ? null : { failed: false, widget: props.widget }
    }

    static getDerivedStateFromError(error: unknown): Partial<TileErrorState> {
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
        if (failed) {
            return (
                <div className="flex h-full items-center justify-center text-secondary text-sm">
                    This widget hit an error.
                </div>
            )
        }
        return this.props.children
    }
}

/**
 * Memoised on the widget, its definition and `setConfig`, which all keep their identity through every layout edit, so
 * moving tiles never re-renders it.
 */
export const WidgetView = memo(function WidgetView({
    widget,
    definition,
    setConfig,
}: WidgetComponentProps & {
    definition: WidgetDefinition | undefined
}): JSX.Element {
    if (!definition) {
        return (
            <div className="flex h-full items-center justify-center text-secondary text-sm">
                This dashboard can't show this widget type.
            </div>
        )
    }
    const Loading: ComponentType<{ widget: ContentWidget }> = definition.Loading ?? WidgetLoading
    // One widget that throws or suspends shows its own state, and the rest of the dashboard keeps working.
    return (
        <TileErrorBoundary widget={widget}>
            <Suspense fallback={<Loading widget={widget} />}>
                <definition.Component widget={widget} setConfig={setConfig} />
            </Suspense>
        </TileErrorBoundary>
    )
})
