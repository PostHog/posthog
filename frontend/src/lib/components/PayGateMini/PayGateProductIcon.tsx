import { Component, type ReactNode, Suspense, lazy } from 'react'

import { cn } from 'lib/utils/css-classes'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { retryImport } from 'lib/utils/retryImport'

// Pay gates ship on every logged-in page, and the brand logo geometry only loads when a gate shows it.
const Logomark = lazy(() => retryImport(() => import('lib/brand')).then((m) => ({ default: m.Logomark })))

// The logomark is decorative, so a chunk that fails to load leaves the space empty. Without this boundary the
// rejection reaches the scene's chunk error boundary, which reloads the whole page.
class LogomarkLoadBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
    override state: { error: unknown } = { error: null }

    static getDerivedStateFromError(error: unknown): { error: unknown } {
        return { error }
    }

    override render(): ReactNode {
        if (!this.state.error) {
            return this.props.children
        }
        if (!isChunkLoadError(this.state.error)) {
            throw this.state.error
        }
        return null
    }
}

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
        <div className="flex h-10 items-center">
            <LogomarkLoadBoundary>
                <Suspense fallback={null}>
                    <Logomark size="xs" />
                </Suspense>
            </LogomarkLoadBoundary>
        </div>
    )
}
