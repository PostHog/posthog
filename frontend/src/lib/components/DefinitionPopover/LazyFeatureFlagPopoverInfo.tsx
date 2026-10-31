import { Suspense, lazy } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { retryImport } from 'lib/utils/retryImport'

// Shared property UI ships on every logged-in page, and the flag lookup only runs inside a popover.
const FeatureFlagPopoverInfo = lazy(() =>
    retryImport(() => import('./FeatureFlagPopoverInfo')).then((m) => ({ default: m.FeatureFlagPopoverInfo }))
)

export function LazyFeatureFlagPopoverInfo({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <Suspense fallback={<Spinner />}>
            <FeatureFlagPopoverInfo flagKey={flagKey} />
        </Suspense>
    )
}
