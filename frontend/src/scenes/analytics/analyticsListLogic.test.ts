import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { resetAnalyticsFeedSnapshot } from './analyticsFeedLogic'
import { analyticsListLogic } from './analyticsListLogic'

const ADA = { id: 1, uuid: 'u-ada', first_name: 'Ada', last_name: '', email: 'ada@example.com' }
const entry = (type: string, ref: string, path: string): Record<string, unknown> => ({
    id: `fs-${ref}`,
    type,
    ref,
    path,
    href: `/x/${ref}`,
    created_at: '2026-09-01T00:00:00Z',
    last_viewed_at: null,
    meta: { created_by: ADA.id },
})

describe('analyticsListLogic', () => {
    let capture: jest.SpyInstance

    beforeEach(() => {
        resetAnalyticsFeedSnapshot()
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    if (params.get('parent')) {
                        return { results: [entry('insight/trends', 'i2', 'Growth/I2')], users: [ADA], next: null }
                    }
                    const type = params.get('type') ?? params.get('type__startswith') ?? ''
                    const results =
                        type === 'insight'
                            ? [
                                  entry('insight/trends', 'i1', 'Growth/I1'),
                                  entry('insight/trends', 'i3', 'Unfiled/Insights/I3'),
                              ]
                            : type === 'notebook'
                              ? [entry('notebook', 'n1', 'Users/Ada/N1')]
                              : []
                    return { results, users: [ADA], next: null }
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        capture.mockRestore()
    })

    it('shows personal rows by default, and hides unfiled and home folder rows on request', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.items.map((item) => item.id).sort()).toEqual(['i1', 'i3', 'n1'])
        logic.actions.setShowPersonal(false)
        expect(logic.values.items.map((item) => item.id)).toEqual(['i1'])
    })

    it('reports a folder visit once, however it starts, and a space only when it changes', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList({ folder: 'Growth' }))
        await expectLogic(logic).toFinishAllListeners()
        router.actions.push(urls.analyticsList({ folder: 'Growth' }))
        await expectLogic(logic).toFinishAllListeners()

        const events = capture.mock.calls
            .filter(([name]) => name !== '$pageview')
            .map(([name, properties]) => [name, properties?.mode ?? properties?.nested])
        expect(events).toEqual([
            ['views list loaded', 'folder'],
            ['analytics space opened', false],
            ['views list loaded', 'folder'],
        ])
    })
})
