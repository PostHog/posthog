import { BatchBudget } from './batch-budget'

describe('BatchBudget', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('shares one unlimited budget that never exhausts and settles to nothing', () => {
        const budget = BatchBudget.unlimited()

        // One instance, so the default feed() argument allocates nothing.
        expect(budget).toBe(BatchBudget.unlimited())
        expect(budget.softAt).toBe(Infinity)
        expect(budget.exhausted).toBe(false)

        jest.advanceTimersByTime(60_000)
        budget.settle()

        expect(budget.exhausted).toBe(false)
    })

    it('exhausts at the soft deadline', () => {
        const budget = BatchBudget.softDeadline(Date.now() + 1000)

        expect(budget.exhausted).toBe(false)

        jest.advanceTimersByTime(999)
        expect(budget.exhausted).toBe(false)

        jest.advanceTimersByTime(1)
        expect(budget.exhausted).toBe(true)
    })

    it('is exhausted straight away when its deadline has already passed', () => {
        // A budget spent on the admission wait has checkpoints to answer before
        // any timer could fire, so construction has to settle this case.
        const budget = BatchBudget.softDeadline(Date.now() - 1)

        expect(budget.exhausted).toBe(true)
    })

    it('stops the deadline from arriving once settled', () => {
        const budget = BatchBudget.softDeadline(Date.now() + 1000)

        budget.settle()
        jest.advanceTimersByTime(5000)

        expect(budget.exhausted).toBe(false)
    })
})
