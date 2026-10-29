import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { UserBasicType } from '~/types'

// pinned: API error codes, match OWNER_LEFT_ORGANIZATION_CODE and OWNER_LOST_ACCESS_CODE in posthog/query_creator_access.py
const OWNER_UNAVAILABLE_CAUSES = {
    owner_left_organization: 'left',
    owner_lost_access: 'lost_access',
} as const

export type OwnerUnavailableCause = (typeof OWNER_UNAVAILABLE_CAUSES)[keyof typeof OWNER_UNAVAILABLE_CAUSES]

export type OwnedResourceLabel = 'subscription' | 'alert'

export type ResourceOwner = Pick<Partial<UserBasicType>, 'first_name' | 'last_name' | 'email'>

/** Why a write was refused because the resource's owner can no longer run it, or null for any other error. */
export function ownerUnavailableCause(error: unknown): OwnerUnavailableCause | null {
    if (!(error instanceof ApiError) || !error.code) {
        return null
    }
    return OWNER_UNAVAILABLE_CAUSES[error.code as keyof typeof OWNER_UNAVAILABLE_CAUSES] ?? null
}

function OwnerUnavailableDescription({
    resourceLabel,
    owner,
    cause,
}: {
    resourceLabel: OwnedResourceLabel
    owner: ResourceOwner | null
    cause: OwnerUnavailableCause
}): JSX.Element {
    return (
        <div className="space-y-2">
            <p className="m-0">
                {resourceLabel === 'alert' ? "Can't enable this alert." : "Can't re-enable this subscription."}
            </p>
            <p className="m-0">
                {owner ? (
                    <>
                        <ProfilePicture user={owner} size="xs" showName />{' '}
                        {cause === 'left'
                            ? 'is no longer in the organization.'
                            : 'no longer has access to the data it reads.'}
                    </>
                ) : (
                    // The owner foreign key is set to null when the account is deleted.
                    "Its owner's account was deleted."
                )}{' '}
                Take ownership to run it with your access.
            </p>
        </div>
    )
}

/**
 * Offer to make the current user the owner of a subscription or alert whose owner can no longer run it.
 * Resolves `true` once `takeOwnership` succeeded, `false` when the dialog was dismissed or the request failed.
 */
export function openTakeOwnershipDialog({
    resourceLabel,
    resourceId,
    owner,
    cause,
    takeOwnership,
}: {
    resourceLabel: OwnedResourceLabel
    resourceId: string | number
    owner: ResourceOwner | null
    cause: OwnerUnavailableCause
    takeOwnership: () => Promise<void>
}): Promise<boolean> {
    return new Promise((resolve) => {
        let taken = false
        let request: Promise<void> = Promise.resolve()
        LemonDialog.open({
            title: `Take ownership of this ${resourceLabel}?`,
            description: <OwnerUnavailableDescription resourceLabel={resourceLabel} owner={owner} cause={cause} />,
            // The modal grows to fit its text, so a long reason would stretch it across the screen.
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
