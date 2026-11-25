import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import hesoyamSfx from 'public/hesoyam.mp3'

import { billingCouponsClaimCreate } from 'products/billing/frontend/generated/api'

import { CheatCodeClaimOutcome, cheatCodeLogic } from './cheatCodeLogic'
import { HesoyamClaimedToast } from './HesoyamClaimedToast'

// pinned: substrings of the billing service's claim error messages. Rewording one there drops it to 'failed'.
const ERROR_OUTCOMES: [string, CheatCodeClaimOutcome][] = [
    ['already claimed', 'already_claimed'],
    ['active subscription', 'needs_billing'],
    ['card on file', 'needs_billing'],
    ['payment method', 'needs_billing'],
    ['maximum number of claims', 'campaign_full'],
    ['card has already been used', 'card_already_used'],
]

export function cheatCodeOutcomeFromError(detail: string): CheatCodeClaimOutcome {
    const lowered = detail.toLowerCase()
    return ERROR_OUTCOMES.find(([text]) => lowered.includes(text))?.[1] ?? 'failed'
}

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

/**
 * Toasts only the outcomes someone can act on. The rest stay silent, so typing the letters by chance doesn't
 * reveal the code; the cheat code page reads every outcome from cheatCodeLogic instead.
 */
export async function claimCheatCode(campaignSlug: string): Promise<CheatCodeClaimOutcome | null> {
    if (claimInFlight) {
        return null
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
        outcome = cheatCodeOutcomeFromError((error?.detail ?? error?.data?.detail ?? '').toString())
        if (outcome === 'already_claimed') {
            lemonToast.info('Nice try. You already used this cheat code.')
        } else if (outcome === 'needs_billing') {
            lemonToast.error('Almost! Cheat codes need billing set up with a card on file. Pay-as-you-go counts.', {
                button: {
                    label: 'Go to billing',
                    action: () => router.actions.push(urls.organizationBilling()),
                    dataAttr: 'cheat-code-go-to-billing',
                },
            })
        }
    } finally {
        claimInFlight = false
    }
    // pinned: analytics event name and properties, used by the HESOYAM dashboard. $current_url shows where it was typed.
    posthog.capture('billing cheat code entered', { campaign_slug: campaignSlug, outcome })
    cheatCodeLogic.findMounted()?.actions.setClaimOutcome(campaignSlug, outcome)
    return outcome
}
