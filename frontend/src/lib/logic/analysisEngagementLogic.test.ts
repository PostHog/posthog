import posthog from 'lib/posthog-typed'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { AnalysisEngagement, analysisEngagementLogic } from './analysisEngagementLogic'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

describe('analysisEngagementLogic', () => {
    let logic: ReturnType<typeof analysisEngagementLogic.build>

    const engagement = (overrides: Partial<AnalysisEngagement> = {}): AnalysisEngagement => ({
        key: 'insight:abc123',
        surface: 'dashboard',
        query: { kind: NodeKind.TrendsQuery, series: [] } as unknown as AnalysisEngagement['query'],
        insightShortId: 'abc123',
        dashboardId: 7,
        isSaved: true,
        dwellMs: 10000,
        ...overrides,
    })

    beforeEach(() => {
        initKeaTests()
        logic = analysisEngagementLogic()
        logic.mount()
        jest.mocked(posthog.capture).mockClear()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('captures which surface and object the user engaged with', () => {
        logic.actions.reportAnalysisEngaged(engagement())

        expect(posthog.capture).toHaveBeenCalledWith(
            'analysis engaged',
            expect.objectContaining({
                surface: 'dashboard',
                insight_short_id: 'abc123',
                dashboard_id: 7,
                is_saved: true,
                dwell_ms: 10000,
                query_kind: NodeKind.TrendsQuery,
                source: 'web',
            })
        )
    })

    it('counts one object once, however often a surface reports it', () => {
        logic.actions.reportAnalysisEngaged(engagement())
        logic.actions.reportAnalysisEngaged(engagement({ dashboardId: 9 }))

        expect(posthog.capture).toHaveBeenCalledTimes(1)
        expect(logic.values.engagedKeys).toEqual(['insight:abc123'])
    })

    it('counts a different object separately', () => {
        logic.actions.reportAnalysisEngaged(engagement())
        logic.actions.reportAnalysisEngaged(engagement({ key: 'insight:def456', insightShortId: 'def456' }))

        expect(posthog.capture).toHaveBeenCalledTimes(2)
    })
})
