import { lazy } from 'react'

// Lazy so the side panel registry doesn't pull Max's thread graph (Query, message widgets)
// into the shell chunk. SidePanel already wraps panel content in a Suspense boundary.
const MaxInstance = lazy(() => import('scenes/max/Max').then((m) => ({ default: m.MaxInstance })))

export function SidePanelMax(): JSX.Element | null {
    return <MaxInstance sidePanel />
}
