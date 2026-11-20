import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import hesoyamSfx from 'public/hesoyam.mp3'

import { billingCouponsClaimCreate } from 'products/billing/frontend/generated/api'

import { HesoyamClaimedToast } from './HesoyamClaimedToast'

export type CheatCodeSource = 'keyboard' | 'coupon_url' | 'coupon_code_field' | 'billing_code_field'
export type CheatCodeClaimOutcome = 'claimed' | 'already_claimed' | 'failed' | 'in_flight'

let claimInFlight = false

function playRewardSound(): void {
    try {
        void new Audio(hesoyamSfx).play()?.catch(() => {})
    } catch {
        // The sound is decoration, so a browser without audio still gets the credit and the toast.
    }
}

/**
 * Claims a cheat code campaign and plays the reward, from any surface that accepts the code.
 * The keyboard shortcut passes `announceFailure: false`, so typing the code by chance doesn't reveal that it exists.
 * Surfaces where the person entered a code on purpose pass `true`, so a failure isn't silent.
 */
export async function claimCheatCode(
    campaignSlug: string,
    { source, announceFailure }: { source: CheatCodeSource; announceFailure: boolean }
): Promise<CheatCodeClaimOutcome> {
    if (claimInFlight) {
        return 'in_flight'
    }
    claimInFlight = true
    let outcome: CheatCodeClaimOutcome
    let errorDetail: string | undefined
    try {
        await billingCouponsClaimCreate({ campaign_slug: campaignSlug })
        outcome = 'claimed'
        playRewardSound()
        lemonToast.success(<HesoyamClaimedToast />)
    } catch (error: any) {
        const detail: string = (error?.detail ?? error?.data?.detail ?? '').toString()
        errorDetail = detail
        if (detail.toLowerCase().includes('already claimed')) {
            outcome = 'already_claimed'
            lemonToast.info('Nice try. You already used this cheat code.')
        } else {
            outcome = 'failed'
            if (announceFailure) {
                lemonToast.error(detail || "Couldn't claim the cheat code. Try again later.")
            }
        }
    } finally {
        claimInFlight = false
    }
    // pinned: analytics event name and properties, used by the HESOYAM dashboard
    posthog.capture('billing cheat code entered', {
        campaign_slug: campaignSlug,
        source,
        outcome,
        error: outcome === 'failed' ? errorDetail || 'Unknown error' : undefined,
    })
    return outcome
}
