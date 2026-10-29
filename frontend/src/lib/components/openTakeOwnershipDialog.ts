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

/**
 * Offer to make the current user the owner of a subscription or alert whose owner can no longer run it.
 * Resolves `true` once `takeOwnership` succeeded, `false` when the dialog was dismissed or the request failed.
 */
export function openTakeOwnershipDialog({
    resourceLabel,
    resourceId,
    takeOwnership,
}: {
    resourceLabel: OwnedResourceLabel
    resourceId: string | number
    takeOwnership: () => Promise<void>
}): Promise<boolean> {
    return new Promise((resolve) => {
        let taken = false
        LemonDialog.open({
            title: `Take ownership of this ${resourceLabel}?`,
            description: `This ${resourceLabel} runs with its owner's access, and the owner can no longer run it. Taking ownership makes you the owner and enables it, so it runs with your access from now on.`,
            shouldAwaitSubmit: true,
            primaryButton: {
                children: 'Take ownership and enable',
                'data-attr': `${resourceLabel}-take-ownership-confirm`,
                onClick: async () => {
                    try {
                        await takeOwnership()
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
            onAfterClose: () => resolve(taken),
        })
    })
}
