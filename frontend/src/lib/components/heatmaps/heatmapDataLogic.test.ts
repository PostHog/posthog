import { heatmapDataLogic, heatmapApiPath, isWithinBounds } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapBoundsFilter, HeatmapFilters, HeatmapKind } from 'lib/components/heatmaps/types'

import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

describe('isWithinBounds', () => {
    const staticArea: HeatmapBoundsFilter = {
        areaFixed: false,
        bounds: { left: 100, right: 200, top: 1000, bottom: 2000 },
    }
    const fixedArea: HeatmapBoundsFilter = {
        areaFixed: true,
        bounds: { left: 100, right: 200, top: 10, bottom: 60 },
    }

    it.each([
        ['no filter keeps every point', { x: 0, y: 0, targetFixed: false }, null, true],
        ['a static point inside a static area', { x: 150, y: 1500, targetFixed: false }, staticArea, true],
        ['a static point outside a static area', { x: 150, y: 100, targetFixed: false }, staticArea, false],
        // points and areas in different coordinate spaces are excluded, not cross-compared
        ['a fixed point against a static area', { x: 150, y: 1500, targetFixed: true }, staticArea, false],
        ['a static point against a fixed area', { x: 150, y: 30, targetFixed: false }, fixedArea, false],
        ['a fixed point inside a fixed area', { x: 150, y: 30, targetFixed: true }, fixedArea, true],
        ['a fixed point outside a fixed area', { x: 150, y: 300, targetFixed: true }, fixedArea, false],
        ['a boundary point is inclusive', { x: 100, y: 1000, targetFixed: false }, staticArea, true],
    ] as const)('%s', (_name, point, filter, expected) => {
        expect(isWithinBounds(point, filter)).toBe(expected)
    })
})

describe('heatmapApiPath', () => {
    let priorAppContext: AppContext | undefined

    beforeEach(() => {
        priorAppContext = window.POSTHOG_APP_CONTEXT
    })

    afterEach(() => {
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it.each([
        // in-app requests must pin the team the page was loaded for, not the user's global current project
        ['in-app', 42, '', '/api/projects/42/heatmaps/'],
        ['in-app', 42, 'events/', '/api/projects/42/heatmaps/events/'],
        // the toolbar has no app context and keeps the legacy unscoped route
        ['toolbar', 42, '', '/api/heatmap/'],
        ['toolbar', 42, 'events/', '/api/heatmap/events/'],
        // without an app context team there is nothing to scope to, so fall back to the legacy route
        ['in-app', null, '', '/api/heatmap/'],
        ['in-app', null, 'events/', '/api/heatmap/events/'],
    ] as const)('context %s with team %s and endpoint %s resolves %s', (context, teamId, endpoint, expected) => {
        window.POSTHOG_APP_CONTEXT = (teamId === null
            ? undefined
            : { current_team: { id: teamId } }) as unknown as AppContext

        expect(heatmapApiPath(context, endpoint)).toBe(expected)
    })
})

describe('heatmapDataLogic empty and sparse detection', () => {
    let logic: ReturnType<typeof heatmapDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = heatmapDataLogic({ context: 'in-app' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    const clickResults = (counts: number[]): Record<string, unknown>[] =>
        counts.map((count) => ({
            count,
            pointer_relative_x: 0.5,
            pointer_target_fixed: false,
            pointer_y: 100,
        }))

    it.each([
        ['no interactions is empty, not sparse', [], true, false, 0],
        ['a handful of clicks is sparse', [2, 1], false, true, 3],
        // threshold is exclusive: a page right at the cutoff is not flagged
        ['clicks at the threshold are not sparse', [10], false, false, 10],
        ['plenty of clicks is neither empty nor sparse', [60], false, false, 60],
    ] as const)('%s', (_name, counts, expectedEmpty, expectedSparse, expectedCount) => {
        logic.actions.loadHeatmapSuccess({ results: clickResults([...counts]) as any })

        expect(logic.values.heatmapEmpty).toBe(expectedEmpty)
        expect(logic.values.heatmapSparse).toBe(expectedSparse)
        expect(logic.values.heatmapInteractionCount).toBe(expectedCount)
    })

    it('never flags scroll depth as sparse, since it is a reach curve rather than an interaction count', () => {
        const filters: HeatmapFilters = {
            enabled: true,
            type: 'scrolldepth' as HeatmapKind,
            viewportAccuracy: 0.9,
            aggregation: 'total_count',
        }
        logic.actions.setHeatmapFilters(filters)
        logic.actions.loadHeatmapSuccess({
            results: [{ scroll_depth_bucket: 100, cumulative_count: 3, bucket_count: 3 }] as any,
        })

        expect(logic.values.heatmapSparse).toBe(false)
    })
})
