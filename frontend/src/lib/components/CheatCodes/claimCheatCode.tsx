import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import hesoyamSfx from 'public/hesoyam.mp3'

import { billingCouponsClaimCreate } from 'products/billing/frontend/generated/api'

import { HesoyamClaimedToast } from './HesoyamClaimedToast'

export type CheatCodeClaimOutcome = 'claimed' | 'already_claimed' | 'failed'

const RECENT_ATTEMPT_WINDOW_MS = 60_000

let claimInFlight = false
let lastAttemptAt = 0

function playRewardSound(): void {
    try {
        void new Audio(hesoyamSfx).play()?.catch(() => {})
    } catch {
        // The sound is decoration, so a browser without audio still gets the credit and the toast.
    }
}

/** True for a minute after someone typed a cheat code, so a coupon field can tell typing from pasting. */
export function cheatCodeTypedRecently(): boolean {
    return Date.now() - lastAttemptAt < RECENT_ATTEMPT_WINDOW_MS
}

/** Errors other than "already claimed" stay silent, so typing the letters by chance doesn't reveal the code. */
export async function claimCheatCode(campaignSlug: string): Promise<void> {
    if (claimInFlight) {
        return
    }
    claimInFlight = true
    lastAttemptAt = Date.now()
    let outcome: CheatCodeClaimOutcome
    try {
        await billingCouponsClaimCreate({ campaign_slug: campaignSlug })
        outcome = 'claimed'
        playRewardSound()
        lemonToast.success(<HesoyamClaimedToast />)
    } catch (error: any) {
        const detail: string = (error?.detail ?? error?.data?.detail ?? '').toString()
        if (detail.toLowerCase().includes('already claimed')) {
            outcome = 'already_claimed'
            lemonToast.info('Nice try. You already used this cheat code.')
        } else {
            outcome = 'failed'
        }
    } finally {
        claimInFlight = false
    }
    // pinned: analytics event name and properties, used by the HESOYAM dashboard. $current_url shows where it was typed.
    posthog.capture('billing cheat code entered', { campaign_slug: campaignSlug, outcome })
}
