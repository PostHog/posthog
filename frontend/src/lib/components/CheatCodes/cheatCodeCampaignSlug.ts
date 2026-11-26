// pinned: campaign slugs the billing service knows. Keep in sync with USER_CLAIMABLE_CAMPAIGN_SLUGS in ee/api/billing.py.
export const HESOYAM_CAMPAIGN_SLUG = 'hesoyam'
const CHEAT_CODE_CAMPAIGN_SLUGS = new Set([HESOYAM_CAMPAIGN_SLUG])

/**
 * Returns the campaign slug when the input is a cheat code, so a coupon field or a `/coupons/<code>` URL
 * can claim it. Case and surrounding whitespace are ignored, because people type it as HESOYAM.
 *
 * @example
 * cheatCodeCampaignSlug(' HESOYAM ') // 'hesoyam'
 * cheatCodeCampaignSlug('LEN-ABC123') // null
 */
export function cheatCodeCampaignSlug(input: string): string | null {
    const normalized = input.trim().toLowerCase()
    return CHEAT_CODE_CAMPAIGN_SLUGS.has(normalized) ? normalized : null
}
