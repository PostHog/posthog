import { z } from 'zod'

import { localStorageSlot } from 'lib/utils/localStorageSlot'

// The verification page loads without a session, so it cannot ask the API which address the code
// went to. The page that starts verification stores the address here, together with the user uuid.
// The verification page shows the address only when the stored uuid matches the uuid in its URL.
// This match prevents one problem: a value left behind by an earlier signup on the same device
// must not name the wrong account.
const pendingVerificationEmailSlot = localStorageSlot(
    'ph_pending_verification_email',
    z.object({ uuid: z.string(), email: z.email() })
)

export function rememberPendingVerificationEmail(uuid: string, email: string): void {
    pendingVerificationEmailSlot.set({ uuid, email })
}

export function pendingVerificationEmailFor(uuid: string | null): string | null {
    const stored = pendingVerificationEmailSlot.get()
    return stored && stored.uuid === uuid ? stored.email : null
}

export function clearPendingVerificationEmail(): void {
    pendingVerificationEmailSlot.clear()
}
