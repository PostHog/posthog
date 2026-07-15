/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalReportRefundSummaryResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxUsageLogic } from './inboxUsageLogic'

const CREDITS_PER_PR = 1500

const mountWithUsage = async (
    currentUsage: number,
    summary: Omit<SignalReportRefundSummaryResponseApi, 'credited_refund_count'>
): Promise<ReturnType<typeof inboxUsageLogic.build>> => {
    useMocks({
        get: {
            '/api/billing': () => [
                200,
                { products: [{ type: 'inbox', display_divisor: CREDITS_PER_PR, current_usage: currentUsage }] },
            ],
            '/api/projects/:team_id/signals/reports/refund-summary/': () => [
                200,
                { credited_refund_count: summary.credited_credits / CREDITS_PER_PR, ...summary },
            ],
        },
    })
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIGNALS_PR_REFUNDS], {
        [FEATURE_FLAGS.SIGNALS_PR_REFUNDS]: true,
    })
    const logic = inboxUsageLogic()
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    return logic
}

describe('inboxUsageLogic', () => {
    let logic: ReturnType<typeof inboxUsageLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // usedPrs must read `max(billing's recorded usage, live billable credits) − credited refunds`:
    // recorded usage lags up to a day, so a just-created PR (and its same-day excluded-path refund)
    // is only visible through the live count, while credited-path refunds stay in recorded usage
    // and must be netted out. Each row pins one side of that contract.
    it.each([
        // [case, billing current_usage, live period credits, credited credits, expected PRs]
        ['counts a just-created PR that billing has not recorded yet', 1500, 3000, 0, 2],
        ['drops when a same-day refund removes the PR from live usage', 1500, 1500, 0, 1],
        ['nets credited-path refunds out of recorded usage', 9000, 9000, 1500, 5],
        ['clamps at zero when credited refunds exceed billed usage', 0, 1500, 3000, 0],
    ])('%s', async (_case, currentUsage, periodBillableCredits, creditedCredits, expectedPrs) => {
        logic = await mountWithUsage(currentUsage, {
            period_billable_credits: periodBillableCredits,
            credited_credits: creditedCredits,
        })

        expect(logic.values.usedPrs).toBe(expectedPrs)
    })
})
