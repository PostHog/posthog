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

describe('healthCategoryDetailLogic', () => {
    let logic: ReturnType<typeof healthCategoryDetailLogic.build>
    let getSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getSpy = jest.spyOn(api, 'get').mockImplementation(async (url: string) => {
            const offset = Number(new URLSearchParams(url.split('?')[1]).get('offset'))
            return { count: 120, results: issues(offset, offset + 50) }
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('shows the server total for a kind and appends the next page on show more', async () => {
        logic = healthCategoryDetailLogic({ category: 'feature_flags' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        expect(getSpy.mock.calls[0][0]).toContain('kind=stale_feature_flags')
        expect(logic.values.issuesByKind[0]).toMatchObject({ count: 120 })
        expect(logic.values.issuesByKind[0].issues).toHaveLength(50)
        expect(logic.values.statusSummary.count).toEqual(120)

        logic.actions.loadMoreIssues('stale_feature_flags')
        await expectLogic(logic).toDispatchActions(['loadMoreIssuesSuccess'])

        expect(getSpy.mock.calls[1][0]).toContain('offset=50')
        expect(logic.values.issuesByKind[0].issues).toHaveLength(100)
        expect(logic.values.issuesByKind[0].issues[50].id).toEqual('flag-50')
        expect(logic.values.loadingMoreKind).toBeNull()
    })
})
