import { expectLogic } from 'kea-test-utils'

import {
    eventFilterParam,
    heatmapApiPath,
    heatmapDataLogic,
    isWithinBounds,
} from 'lib/components/heatmaps/heatmapDataLogic'
import { CommonFilters, HeatmapBoundsFilter } from 'lib/components/heatmaps/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
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

describe('eventFilterParam', () => {
    it.each([
        ['no events', undefined, undefined],
        ['an empty list', [], undefined],
        // ActionFilter adds the row before the user picks an event, and the API rejects a null id.
        ['only rows without a picked event', [{ id: null }, { id: null }], undefined],
        ['a mix of picked and unpicked rows', [{ id: null }, { id: 'purchase' }], '[{"id":"purchase"}]'],
        [
            'the property filters a picked row carries',
            [{ id: 'purchase', properties: [{ type: 'event', key: 'plan', value: 'pro' }] }],
            '[{"id":"purchase","properties":[{"type":"event","key":"plan","value":"pro"}]}]',
        ],
    ] as const)('%s', (_name, events, expected) => {
        expect(eventFilterParam(events as CommonFilters['events'])).toBe(expected)
    })
})

describe('heatmapDataLogic requests', () => {
    let logic: ReturnType<typeof heatmapDataLogic.build>

    const mountToolbar = (accessToken?: string): void => {
        toolbarConfigLogic.build({ apiURL: 'http://localhost', accessToken }).mount()
    }

    beforeAll(silenceKeaLoadersErrors)
    afterAll(resumeKeaLoadersErrors)

    beforeEach(() => {
        initKeaTests()
        global.fetch = jest.fn(() =>
            Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ results: [] }) } as any as Response)
        )
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('makes no request while the toolbar is still authenticating', async () => {
        mountToolbar()
        logic = heatmapDataLogic({ context: 'toolbar' })
        logic.mount()
        ;(global.fetch as jest.Mock).mockClear()

        await expectLogic(logic, () => {
            logic.actions.setHref('https://example.com/pricing')
        }).toDispatchActions(['loadHeatmapSuccess'])

        // A request now answers with the transport's stub 401, which the user cannot act on.
        expect((global.fetch as jest.Mock).mock.calls).toHaveLength(0)
    })

    it('sends the user back through OAuth when the heatmap request is rejected', async () => {
        mountToolbar('access-token')
        logic = heatmapDataLogic({ context: 'toolbar' })
        logic.mount()
        ;(global.fetch as jest.Mock).mockImplementation(() =>
            Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as any as Response)
        )

        await expectLogic(toolbarConfigLogic, () => {
            logic.actions.setHref('https://example.com/pricing')
        }).toDispatchActions(['authenticate'])
    })

    it('reports a heatmap export that has no access token', async () => {
        const toastError = jest.spyOn(lemonToast, 'error').mockImplementation()
        logic = heatmapDataLogic({ context: 'in-app', exportToken: '' })
        logic.mount()
        ;(global.fetch as jest.Mock).mockClear()

        await expectLogic(logic, () => {
            logic.actions.setHref('https://example.com/pricing')
        }).toDispatchActions(['loadHeatmapFailure'])

        // An unauthenticated request can only answer 401, which tells the user nothing.
        expect((global.fetch as jest.Mock).mock.calls).toHaveLength(0)
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining('missing its access token'))
        toastError.mockRestore()
    })
})
