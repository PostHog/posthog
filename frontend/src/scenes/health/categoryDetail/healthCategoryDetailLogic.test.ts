import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { healthCategoryDetailLogic } from './healthCategoryDetailLogic'

const issues = (from: number, to: number): Record<string, unknown>[] =>
    Array.from({ length: to - from }, (_, index) => ({
        id: `flag-${from + index}`,
        kind: 'stale_feature_flags',
        severity: 'info',
        payload: {},
        dismissed: false,
        snoozed_until: null,
    }))

const offsetOf = (url: string): number => Number(new URLSearchParams(url.split('?')[1]).get('offset'))

describe('healthCategoryDetailLogic', () => {
    let logic: ReturnType<typeof healthCategoryDetailLogic.build>
    let getSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getSpy = jest.spyOn(api, 'get')
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('shows the server total and pages by server offset when a page overlaps the rows already shown', async () => {
        const pages: Record<number, Record<string, unknown>[]> = {
            0: issues(0, 50),
            50: issues(49, 99),
            100: issues(100, 101),
        }
        getSpy.mockImplementation(async (url: string) => ({ count: 101, results: pages[offsetOf(url)] }))

        logic = healthCategoryDetailLogic({ category: 'feature_flags' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        expect(getSpy.mock.calls[0][0]).toContain('kind=stale_feature_flags')
        expect(logic.values.issuesByKind[0]).toMatchObject({ count: 101, remaining: 51 })
        expect(logic.values.statusSummary.count).toEqual(101)

        logic.actions.loadMoreIssues('stale_feature_flags')
        await expectLogic(logic).toDispatchActions(['loadMoreIssuesSuccess'])
        expect(offsetOf(getSpy.mock.calls[1][0])).toEqual(50)
        expect(logic.values.issuesByKind[0].issues).toHaveLength(99)
        expect(logic.values.issuesByKind[0].remaining).toEqual(1)

        logic.actions.loadMoreIssues('stale_feature_flags')
        await expectLogic(logic).toDispatchActions(['loadMoreIssuesSuccess'])
        expect(offsetOf(getSpy.mock.calls[2][0])).toEqual(100)
        expect(logic.values.issuesByKind[0].issues).toHaveLength(100)
        expect(logic.values.nextKindWithMore).toBeNull()
    })

    it('drops a show more response that a reload overtook', async () => {
        let releaseNextPage: (value: unknown) => void = () => {}
        getSpy.mockImplementation(async (url: string) =>
            offsetOf(url) === 50
                ? new Promise((resolve) => {
                      releaseNextPage = resolve
                  })
                : { count: 120, results: issues(0, 50) }
        )

        logic = healthCategoryDetailLogic({ category: 'feature_flags' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        logic.actions.loadMoreIssues('stale_feature_flags')
        logic.actions.loadHealthIssues()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])
        releaseNextPage({ count: 120, results: issues(50, 100) })
        await expectLogic(logic).toDispatchActions(['loadMoreIssuesSuccess'])

        expect(logic.values.issuesByKind[0].issues).toHaveLength(50)
        expect(logic.values.issuesByKind[0].remaining).toEqual(70)
    })
})
