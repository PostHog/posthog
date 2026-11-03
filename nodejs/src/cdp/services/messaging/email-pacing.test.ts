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
        tiers.getEmailSendingTier.mockReset()
    })

    it.each([
        ['a tier above the table', 9, 0, '50 emails per hour'],
        ['a tier above the table', 9, 1, '200 emails per day'],
        ['a negative tier', -1, 1, '20 emails per day'],
    ])('names the nearest tier cap for %s (tier %i, bucket %i denies)', async (_name, tier, deniedIndex, cap) => {
        tiers.getEmailSendingTier.mockResolvedValue(tier)
        limiter.claimAllOrNothingPair.mockResolvedValue({
            granted: false,
            deniedIndex,
            retryAfterMs: 4000,
            reserved: true,
        })

        expect(await enforce.claim(invocation, false)).toEqual({
            retryDelayMs: 4000,
            logMessage: `This project reached its email sending limit of ${cap}. Retrying this email in 4s. The limit rises as the project builds a clean sending history.`,
        })
    })
})
