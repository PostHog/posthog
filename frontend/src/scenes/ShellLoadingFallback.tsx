import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'

// A stalled lazy import for the app shell never rejects, so ChunkLoadErrorBoundary cannot catch it
// and Suspense keeps its fallback forever. After this delay we assume the request has stalled and
// offer a manual reload so the user is not trapped on a loading screen.
const SHELL_STALL_TIMEOUT_MS = 15_000

/** Suspense fallback for the authenticated app shell. Spins, then offers a reload if it stalls. */
export function ShellLoadingFallback(): JSX.Element {
    const [stalled, setStalled] = useState(false)

    useEffect(() => {
        const timeout = window.setTimeout(() => setStalled(true), SHELL_STALL_TIMEOUT_MS)
        return () => window.clearTimeout(timeout)
    }, [])

    return (
        <div className="relative h-screen">
            <SpinnerOverlay sceneLevel />
            {stalled && (
                // Sit above the scene-level SpinnerOverlay, which uses --z-content-overlay.
                <div className="absolute inset-x-0 bottom-16 z-[calc(var(--z-content-overlay)+1)] flex flex-col items-center gap-2 px-4 text-center">
                    <p className="text-secondary">This is taking longer than usual to load.</p>
                    <LemonButton type="primary" onClick={() => window.location.reload()}>
                        Reload page
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
