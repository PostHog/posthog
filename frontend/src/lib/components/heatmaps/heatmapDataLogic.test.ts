import { heatmapApiPath, isWithinBounds } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapBoundsFilter } from 'lib/components/heatmaps/types'

import { AppContext } from '~/types'

describe('isWithinBounds', () => {
    const boundsFilter: HeatmapBoundsFilter = {
        documentBounds: { left: 100, right: 200, top: 1000, bottom: 2000 },
        viewportBounds: { left: 100, right: 200, top: 10, bottom: 60 },
    }

    it.each([
        ['no filter keeps every point', { x: 0, y: 0, targetFixed: false }, null, true],
        ['a document point inside the document bounds', { x: 150, y: 1500, targetFixed: false }, boundsFilter, true],
        ['a document point outside the document bounds', { x: 150, y: 100, targetFixed: false }, boundsFilter, false],
        // fixed targets are recorded in viewport coordinates, so y=30 is inside for fixed but outside for static
        ['a fixed point tested against the viewport bounds', { x: 150, y: 30, targetFixed: true }, boundsFilter, true],
        ['a fixed point outside the viewport bounds', { x: 150, y: 1500, targetFixed: true }, boundsFilter, false],
        ['a boundary point is inclusive', { x: 100, y: 1000, targetFixed: false }, boundsFilter, true],
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
