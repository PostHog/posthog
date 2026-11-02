import clsx from 'clsx'
import { Suspense } from 'react'

import { IconSupport } from '@posthog/icons'
import { PostHogErrorBoundary } from '@posthog/react'

import { lazyWithRetry } from 'lib/utils/retryImport'

// The unread count comes from the support ticket logic, which holds the whole ticket flow.
const SidePanelSupportIcon = lazyWithRetry(() =>
    import('products/conversations/frontend/components/SidePanel/SidePanelSupportIcon').then((m) => ({
        default: m.SidePanelSupportIcon,
    }))
)

/** The support tab icon. It shows the unread count when its chunk has loaded. */
export function LazySidePanelSupportIcon({ className }: { className?: string }): JSX.Element {
    const plainIcon = (
        <span className={clsx('relative inline-flex', className)}>
            <IconSupport />
        </span>
    )
    // Not ChunkLoadErrorBoundary: a missing unread badge does not justify reloading the page.
    return (
        <PostHogErrorBoundary fallback={plainIcon}>
            <Suspense fallback={plainIcon}>
                <SidePanelSupportIcon className={className} />
            </Suspense>
        </PostHogErrorBoundary>
    )
}
