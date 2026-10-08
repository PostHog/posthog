import { useEffect, useState } from 'react'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'

// A short delay keeps a cached chunk from opening this modal for one frame before the real one.
const SHOW_AFTER_MS = 200

/** Suspense fallback for a lazily loaded dashboard modal, so the click that opened it gets a response. */
export function DashboardModalLoading({
    isOpen,
    onClose,
    label = 'Loading',
}: {
    isOpen: boolean
    onClose: () => void
    label?: string
}): JSX.Element | null {
    const [visible, setVisible] = useState(false)

    useEffect(() => {
        const timeoutId = window.setTimeout(() => setVisible(true), SHOW_AFTER_MS)
        return () => window.clearTimeout(timeoutId)
    }, [])

    return visible ? (
        <LemonModal isOpen={isOpen} onClose={onClose} simple>
            {/* role="status" with a name gives the spinner-only dialog an accessible loading announcement. */}
            <div role="status" aria-label={label} className="flex justify-center p-8">
                <Spinner />
            </div>
        </LemonModal>
    ) : null
}
