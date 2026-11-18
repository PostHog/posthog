import { Suspense, lazy } from 'react'

import { cn } from 'lib/utils/css-classes'
import { retryImport } from 'lib/utils/retryImport'

// Pay gates ship on every logged-in page, and the brand logo geometry only loads when a gate shows it.
const Logomark = lazy(() => retryImport(() => import('lib/brand')).then((m) => ({ default: m.Logomark })))

/** A feature's product icon, or the theme-aware PostHog logomark when the feature has none. */
export function PayGateProductIcon({
    productIcon,
    iconClassName,
}: {
    productIcon: JSX.Element | null
    /** Tints the product icon. The logomark keeps its brand colors. */
    iconClassName: string
}): JSX.Element {
    if (productIcon) {
        return <div className={cn('flex text-4xl', iconClassName)}>{productIcon}</div>
    }

    return (
        <div className="flex h-8 items-center">
            <Suspense fallback={null}>
                <Logomark size="lg" />
            </Suspense>
        </div>
    )
}
