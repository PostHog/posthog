import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { resetViewFeedSnapshot } from './viewFeedLogic'
import { typeFilterFromUrl, viewsLogic } from './viewsLogic'

describe('viewsLogic', () => {
    beforeEach(() => {
        resetViewFeedSnapshot()
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/dashboards/': { results: [], next: null },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    it('loads the list in the standard navigation when small software apps are on', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SMALL_SOFTWARE_APPS]: true })
        const logic = viewsLogic()
        logic.mount()

        router.actions.push(urls.views())
        await expectLogic(logic).toDispatchActions(['loadViews'])
    })

    it('loads nothing when neither navigation flag is on', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = viewsLogic()
        logic.mount()

        router.actions.push(urls.views())
        await expectLogic(logic).toNotHaveDispatchedActions(['loadViews'])
    })

    it('preselects the type filter from the url', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SMALL_SOFTWARE_APPS]: true })
        const logic = viewsLogic()
        logic.mount()

        router.actions.push(urls.views(), { type: 'canvas' })
        await expectLogic(logic).toDispatchActions(['applyTypeFilterFromUrl', 'loadViews'])
        expect(logic.values.typeFilter).toEqual('canvas')

        router.actions.push(urls.views(), { type: 'not-a-view-type' })
        await expectLogic(logic).toDispatchActions(['loadViews'])
        expect(logic.values.typeFilter).toEqual('canvas')
    })

    it('clears the url filter when the url asks for the full list', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SMALL_SOFTWARE_APPS]: true })
        const logic = viewsLogic()
        logic.mount()

        router.actions.push(urls.views(), { type: 'canvas' })
        await expectLogic(logic).toDispatchActions(['applyTypeFilterFromUrl', 'loadViews'])
        expect(logic.values.typeFilter).toEqual('canvas')

        router.actions.push(urls.views())
        await expectLogic(logic).toDispatchActions(['applyTypeFilterFromUrl', 'loadViews'])
        expect(logic.values.typeFilter).toEqual('all')

        router.actions.push(urls.views(), { type: 'canvas' })
        await expectLogic(logic).toDispatchActions(['applyTypeFilterFromUrl', 'loadViews'])
        router.actions.push(urls.views(), { type: 'all' })
        await expectLogic(logic).toDispatchActions(['applyTypeFilterFromUrl', 'loadViews'])
        expect(logic.values.typeFilter).toEqual('all')
    })

    it.each(['toString', 'constructor', '__proto__'])('ignores the inherited name %s as a type filter', (type) => {
        expect(typeFilterFromUrl(type)).toBeNull()
    })
})
