import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AI_CREDITS_POLL_INTERVAL_MS, aiCreditsLogic } from './aiCreditsLogic'

describe('aiCreditsLogic', () => {
    let logic: ReturnType<typeof aiCreditsLogic.build>
    // The status of the one top-up each read returns, in order; 'error' answers with a 500.
    let statuses: string[]
    let reads: number

    beforeEach(() => {
        reads = 0
        useMocks({
            get: {
                '/api/billing/ai-credits/': () => {
                    const status = statuses[Math.min(reads, statuses.length - 1)]
                    reads += 1
                    if (status === 'error') {
                        return [500, { detail: 'Unavailable' }]
                    }
                    return [
                        200,
                        {
                            available: true,
                            balance_usd: '10.00',
                            amounts_usd: [10, 25],
                            top_ups: [
                                {
                                    id: 1,
                                    amount_usd: '25.00',
                                    status,
                                    failure_reason: null,
                                    created_at: '2026-10-02T09:00:00Z',
                                },
                            ],
                        },
                    ]
                },
            },
            post: {
                '/api/billing/ai-credits/top-up/': () => [200, { status: 'rejected', reason: 'no_payment_method' }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('polls through a failed read while a top-up processes, and stops once it is credited', async () => {
        jest.useFakeTimers()
        const toastError = jest.spyOn(lemonToast, 'error')
        statuses = ['awaiting_tax', 'error', 'credited']
        logic = aiCreditsLogic()
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(reads).toBe(1)

        await jest.advanceTimersByTimeAsync(AI_CREDITS_POLL_INTERVAL_MS)
        expect(reads).toBe(2)
        expect(logic.values.inFlightTopUp?.status).toBe('awaiting_tax')
        expect(toastError).not.toHaveBeenCalled()

        await jest.advanceTimersByTimeAsync(AI_CREDITS_POLL_INTERVAL_MS)
        expect(reads).toBe(3)
        expect(logic.values.inFlightTopUp).toBeNull()

        await jest.advanceTimersByTimeAsync(AI_CREDITS_POLL_INTERVAL_MS * 3)
        expect(reads).toBe(3)
    })

    it('tells the user why billing refused a top-up', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        statuses = ['credited']
        logic = aiCreditsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadAiCreditsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.topUp(25)
        })
            .toDispatchActions(['topUpSuccess', 'loadAiCreditsSuccess'])
            .toMatchValues({ topUpResponseLoading: false, pendingTopUpAmount: null })
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining('payment card'))
    })
})
