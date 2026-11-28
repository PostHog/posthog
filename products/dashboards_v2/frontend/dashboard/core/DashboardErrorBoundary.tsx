import posthog from 'posthog-js'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

import type { Dashboard } from '../document/dashboardTypes'
import { DashboardUnavailable } from './DashboardUnavailable'

type DashboardErrorState = {
    failed: boolean
    error?: unknown
    dashboard: Dashboard
}

/** The fallback for an error no panel boundary caught, such as one in the grid, a section or the filter bar. */
export class DashboardErrorBoundary extends Component<
    { dashboard: Dashboard; children: ReactNode },
    DashboardErrorState
> {
    override state: DashboardErrorState = { failed: false, dashboard: this.props.dashboard }

    // A new document from the host, such as an undo or a reload, gets another try.
    static getDerivedStateFromProps(
        props: { dashboard: Dashboard },
        state: DashboardErrorState
    ): DashboardErrorState | null {
        return props.dashboard === state.dashboard ? null : { failed: false, dashboard: props.dashboard }
    }

    static getDerivedStateFromError(error: unknown): Partial<DashboardErrorState> {
        return { failed: true, error }
    }

    override componentDidCatch(error: Error, info: ErrorInfo): void {
        if (isChunkLoadError(error)) {
            return
        }
        posthog.captureException(error, { tag: 'dashboards-v2-dashboard', componentStack: info.componentStack })
    }

    override render(): ReactNode {
        // A panel's failed code download goes on up to the app's chunk boundary, which reloads the page.
        if (this.state.failed && isChunkLoadError(this.state.error)) {
            throw this.state.error
        }
        return this.state.failed ? <DashboardUnavailable problem="error" /> : this.props.children
    }
}
