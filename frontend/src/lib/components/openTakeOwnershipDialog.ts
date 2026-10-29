import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

// pinned: API error code, matches OWNER_UNAVAILABLE_CODE in posthog/query_creator_access.py
export const OWNER_UNAVAILABLE_CODE = 'owner_unavailable'

export type OwnedResourceLabel = 'subscription' | 'alert'

/** True when a write was refused because the resource's owner can no longer run it. */
export function isOwnerUnavailableError(error: unknown): boolean {
    return error instanceof ApiError && error.code === OWNER_UNAVAILABLE_CODE
}

/** The server's explanation of a refused enable, when the error carries one. */
export function ownerUnavailableReason(error: unknown): string | null {
    return error instanceof ApiError && error.detail ? error.detail : null
}

/**
 * Offer to make the current user the owner of a subscription or alert whose owner can no longer run it.
 * `reason` is the server's explanation, which names the owner and why they cannot run it.
 * Resolves `true` once `takeOwnership` succeeded, `false` when the dialog was dismissed or the request failed.
 */
export function openTakeOwnershipDialog({
    resourceLabel,
    resourceId,
    reason,
    takeOwnership,
}: {
    resourceLabel: OwnedResourceLabel
    resourceId: string | number
    reason: string | null
    takeOwnership: () => Promise<void>
}): Promise<boolean> {
    return new Promise((resolve) => {
        let taken = false
        let request: Promise<void> = Promise.resolve()
        LemonDialog.open({
            title: `Take ownership of this ${resourceLabel}?`,
            description:
                reason ??
                `This ${resourceLabel} runs with its owner's access, and the owner can no longer run it. Take ownership to run it with your access.`,
            // Two sentences of copy; the default dialog width spans the screen.
            maxWidth: '30rem',
            shouldAwaitSubmit: true,
            primaryButton: {
                children: 'Take ownership and enable',
                'data-attr': `${resourceLabel}-take-ownership-confirm`,
                onClick: async () => {
                    request = takeOwnership()
                    try {
                        await request
                    } catch (error) {
                        const detail = error instanceof ApiError ? error.detail : null
                        lemonToast.error(detail || `Could not take ownership of this ${resourceLabel}. Try again.`)
                        return
                    }
                    taken = true
                    posthog.capture(`${resourceLabel} ownership taken`, { [`${resourceLabel}_id`]: resourceId })
                },
            },
            secondaryButton: { children: 'Cancel', 'data-attr': `${resourceLabel}-take-ownership-cancel` },
            // A dismissal while the request is in flight waits for it, so a takeover that lands is still reported.
            onAfterClose: () => {
                void request.then(
                    () => resolve(taken),
                    () => resolve(taken)
                )
            },
        })
    })
}
