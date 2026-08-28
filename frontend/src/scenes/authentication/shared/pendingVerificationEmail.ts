import { z } from 'zod'

import { localStorageSlot } from 'lib/utils/localStorageSlot'

// An unverified user has no session, so the verification page cannot ask the API which address it is
// waiting on. The device that signed up leaves the address here, so the page can name it. Absent
// when the person opens the page somewhere else — the copy falls back to not naming an address.
export const pendingVerificationEmailStorage = localStorageSlot('ph_pending_verification_email', z.email())
