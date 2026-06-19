import { heatmapApiPath } from 'lib/components/heatmaps/heatmapDataLogic'

import { AppContext } from '~/types'

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
