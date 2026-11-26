import posthog from 'posthog-js'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { DashboardUnavailable } from './DashboardUnavailable'
import type { Dashboard } from './document/dashboardTypes'

type DashboardErrorState = {
    failed: boolean
    dashboard: Dashboard
}

/** The fallback for an error no widget boundary caught, such as one in the grid, a section or the filter bar. */
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

    static getDerivedStateFromError(): Partial<DashboardErrorState> {
        return { failed: true }
    }

    override componentDidCatch(error: Error, info: ErrorInfo): void {
        posthog.captureException(error, { tag: 'dashboards-v2-dashboard', componentStack: info.componentStack })
    }

    override render(): ReactNode {
        return this.state.failed ? <DashboardUnavailable problem="error" /> : this.props.children
    }
}
