import { type DashboardLoadReport, createDashboardTiming } from './dashboardTiming'

describe('createDashboardTiming', () => {
    let clock: number
    let settled: boolean
    let reports: DashboardLoadReport[]
    const timing = (): ReturnType<typeof createDashboardTiming> =>
        createDashboardTiming({ isSettled: () => settled, onReport: (r) => reports.push(r), now: () => clock })

    beforeEach(() => {
        jest.useFakeTimers()
        clock = 0
        settled = true
        reports = []
    })

    afterEach(() => jest.useRealTimers())

    it('ends a load at its last query, only once no tile waits to mount', () => {
        const t = timing()
        t.begin('load')
        const first = t.started(false)
        const second = t.started(true)
        clock = 40
        first('success')
        settled = false
        clock = 90
        second('error')
        jest.advanceTimersByTime(500)
        expect(reports).toEqual([])

        const late = t.started(false)
        clock = 300
        late('success')
        settled = true
        jest.advanceTimersByTime(500)

        expect(reports).toEqual([
            expect.objectContaining({
                trigger: 'load',
                status: 'success',
                durationMs: 300,
                firstResultMs: 40,
                queryCount: 3,
                cachedQueryCount: 1,
                failedQueryCount: 1,
            }),
        ])
    })

    it('reports a load cut short by another as abandoned', () => {
        const t = timing()
        t.begin('load')
        const slow = t.started(false)
        t.begin('refresh')
        slow('success')
        t.started(false)('success')
        jest.advanceTimersByTime(500)

        expect(reports.map(({ trigger, status, queryCount }) => [trigger, status, queryCount])).toEqual([
            ['load', 'abandoned', 1],
            ['refresh', 'success', 1],
        ])
    })
})
