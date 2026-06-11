import { Suspense, lazy } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'

const MaxInstance = lazy(() => import('scenes/max/Max').then((m) => ({ default: m.MaxInstance })))

/** Lazy so the side panel registry doesn't pull Max's thread graph (Query, message widgets) into the shell chunk. */
export function SidePanelMax(): JSX.Element | null {
    return (
        <Suspense fallback={<Spinner className="m-4" />}>
            <MaxInstance sidePanel />
        </Suspense>
    )
}
