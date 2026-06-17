import { expectLogic } from 'kea-test-utils'

import { heatmapApiPath, heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { AppContext } from '~/types'

describe('heatmapDataLogic', () => {
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

    describe('loadHeatmap auth handling (toolbar)', () => {
        let logic: ReturnType<typeof heatmapDataLogic.build>

        beforeEach(() => {
            initKeaTests()
            toolbarConfigLogic
                .build({
                    apiURL: 'http://localhost',
                    accessToken: 'test-token',
                    refreshToken: 'test-refresh',
                    clientId: 'test-client',
                })
                .mount()
            logic = heatmapDataLogic({ context: 'toolbar' })
            logic.mount()
        })

        it('re-authenticates and returns gracefully on a 401 instead of throwing', async () => {
            // Token refresh also fails, so the invalid-token 401 flows back to the loader.
            global.fetch = jest.fn((url: RequestInfo | URL) => {
                if (typeof url === 'string' && url.includes('toolbar_oauth_refresh')) {
                    return Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({}) } as Response)
                }
                return Promise.resolve({
                    ok: false,
                    status: 401,
                    json: () => Promise.resolve({ detail: 'Invalid access token.' }),
                } as Response)
            }) as jest.Mock

            await expectLogic(logic, () => {
                logic.actions.setHref('https://example.com')
            })
                .toDispatchActions(['loadHeatmap', toolbarConfigLogic.actionTypes.tokenExpired, 'loadHeatmapSuccess'])
                .toNotHaveDispatchedActions(['loadHeatmapFailure'])
                .toMatchValues({ rawHeatmap: null, isReady: true })
        })

        it('triggers authentication and returns gracefully on a 403 instead of throwing', async () => {
            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: false,
                    status: 403,
                    json: () => Promise.resolve({ detail: 'You do not have access to this project.' }),
                } as Response)
            ) as jest.Mock

            await expectLogic(logic, () => {
                logic.actions.setHref('https://example.com')
            })
                .toDispatchActions(['loadHeatmap', toolbarConfigLogic.actionTypes.authenticate, 'loadHeatmapSuccess'])
                .toNotHaveDispatchedActions(['loadHeatmapFailure'])
                .toMatchValues({ rawHeatmap: null })
        })
    })
})
