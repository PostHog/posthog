import { BatchBudget } from './batch-budget'

describe('BatchBudget', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('shares one unlimited budget that never exhausts', () => {
        const budget = BatchBudget.unlimited()

        expect(budget).toBe(BatchBudget.unlimited())
        expect(budget.softAt).toBe(Infinity)
        expect(budget.exhausted).toBe(false)

        jest.advanceTimersByTime(60_000)

        expect(budget.exhausted).toBe(false)
    })

    // setSystemTime moves the clock without running timers, as a synchronous step that holds the event loop does.
    it('exhausts at the soft deadline even when no timer has run', () => {
        const now = Date.now()
        const budget = BatchBudget.softDeadline(now + 1000)

        jest.setSystemTime(now + 999)
        expect(budget.exhausted).toBe(false)

        jest.setSystemTime(now + 1000)
        expect(budget.exhausted).toBe(true)
    })

    it('stays exhausted when the wall clock steps back', () => {
        const now = Date.now()
        const budget = BatchBudget.softDeadline(now + 1000)

        jest.setSystemTime(now + 1000)
        expect(budget.exhausted).toBe(true)

        jest.setSystemTime(now)
        expect(budget.exhausted).toBe(true)
    })

    it('is exhausted straight away when its deadline has already passed', () => {
        const budget = BatchBudget.softDeadline(Date.now() - 1)

        expect(budget.exhausted).toBe(true)
    })
})
