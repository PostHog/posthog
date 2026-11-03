import { createExampleInvocation } from '~/cdp/_tests/fixtures'

import type { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import type { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { TeamSendingCap } from './email-pacing'

describe('TeamSendingCap.claim', () => {
    const limiter = { claimAllOrNothingPair: jest.fn() }
    const tiers = { getEmailSendingTier: jest.fn() }
    const invocation = createExampleInvocation({ team_id: 7 })
    const enforce = new TeamSendingCap(
        limiter as unknown as RateLimiterService,
        tiers as unknown as TeamWorkflowsConfigService,
        { teamEmailCapMode: 'enforce', teamEmailTierHourlyCaps: [5, 50], teamEmailTierDailyCaps: [20, 200] }
    )

    beforeEach(() => {
        limiter.claimAllOrNothingPair.mockReset()
        tiers.getEmailSendingTier.mockReset().mockResolvedValue(0)
    })

    it.each([
        ['a tier above the table', 9, 50, 200],
        ['a negative tier', -1, 5, 20],
    ])('caps %s at the nearest tier in the table', async (_name, tier, hourly, daily) => {
        tiers.getEmailSendingTier.mockResolvedValue(tier)
        limiter.claimAllOrNothingPair.mockResolvedValue({
            granted: true,
            deniedIndex: null,
            retryAfterMs: null,
            reserved: false,
        })

        expect(await enforce.claim(invocation, false)).toBeNull()
        const [buckets] = limiter.claimAllOrNothingPair.mock.calls[0]
        expect(buckets.map((bucket: { capacity: number }) => bucket.capacity)).toEqual([hourly, daily])
    })

    it('parks a send the daily bucket denies and names the daily cap', async () => {
        limiter.claimAllOrNothingPair.mockResolvedValue({
            granted: false,
            deniedIndex: 1,
            retryAfterMs: 4000,
            reserved: true,
        })

        expect(await enforce.claim(invocation, false)).toEqual({
            retryDelayMs: 4000,
            logMessage:
                'This project reached its email sending limit of 20 emails per day. Retrying this email in 4s. The limit rises as the project builds a clean sending history.',
        })
    })
})
