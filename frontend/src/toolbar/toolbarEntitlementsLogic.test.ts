import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarEntitlementsLogic } from '~/toolbar/toolbarEntitlementsLogic'
import { AvailableFeature } from '~/types'

describe('toolbarEntitlementsLogic', () => {
    let logic: ReturnType<typeof toolbarEntitlementsLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
        logic = toolbarEntitlementsLogic()
        logic.mount()
    })

    it.each([
        ['unknown', null, true],
        ['explicitly false', { toolbar_heatmaps: false }, false],
        ['explicitly true', { toolbar_heatmaps: true }, true],
    ])('isEntitled fails open unless a feature is %s', (_desc, payload, expected) => {
        logic.actions.loadEntitlementsSuccess(payload as Record<string, boolean> | null)
        expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(expected)
    })

    it('loads the entitlement map from the endpoint', async () => {
        useMocks({
            get: {
                '/api/user/toolbar_entitlements': () => ({ entitlements: { toolbar_heatmaps: false } }),
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadEntitlements()
        })
            .toDispatchActions(['loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: { toolbar_heatmaps: false } })

        expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(false)
    })

    it('fails open when the endpoint denies access', async () => {
        useMocks({
            get: {
                '/api/user/toolbar_entitlements': () => [403, {}],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadEntitlements()
        })
            .toDispatchActions(['loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: null })

        expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(true)
    })
})
