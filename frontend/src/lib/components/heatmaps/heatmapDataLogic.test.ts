import { heatmapApiPath, isWithinBounds } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapBoundsFilter } from 'lib/components/heatmaps/types'

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
