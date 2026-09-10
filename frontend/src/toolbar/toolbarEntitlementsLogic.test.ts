import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { heatmapToolbarMenuLogic } from '~/toolbar/elements/heatmapToolbarMenuLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import {
    ToolbarEntitlements,
    ToolbarFeatureGateStatus,
    isToolbarFeatureGated,
    toolbarEntitlementsLogic,
    toolbarFeatureGateStatus,
} from '~/toolbar/toolbarEntitlementsLogic'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { AvailableFeature } from '~/types'

describe('toolbarEntitlementsLogic', () => {
    let logic: ReturnType<typeof toolbarEntitlementsLogic.build>

    beforeEach(() => {
        initKeaTests()
        toolbarPosthogJS.stopSessionRecording = jest.fn()
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
        logic = toolbarEntitlementsLogic()
        logic.mount()
    })

    it.each([
        ['unknown', null, false],
        ['missing', {}, false],
        ['explicitly false', { toolbar_heatmaps: false }, false],
        ['explicitly true', { toolbar_heatmaps: true }, true],
    ])('isEntitled requires confirmation when a feature is %s', (_desc, payload, expected) => {
        logic.actions.loadEntitlementsSuccess(payload as Record<string, boolean> | null)
        expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(expected)
    })

    it.each<[ToolbarFeatureGateStatus, string, boolean, ToolbarEntitlements | null, boolean]>([
        ['available', 'the rollout is off', false, null, false],
        ['checking', 'the request is pending', true, null, true],
        ['unknown', 'the request failed', true, null, false],
        ['unknown', 'the feature is missing', true, {}, false],
        ['locked', 'the feature is false', true, { toolbar_heatmaps: false }, false],
        ['available', 'the feature is true', true, { toolbar_heatmaps: true }, false],
    ])('reports the gate as %s when %s', (expected, _desc, rolloutEnabled, entitlements, entitlementsLoading) => {
        expect(
            toolbarFeatureGateStatus(
                AvailableFeature.TOOLBAR_HEATMAPS,
                rolloutEnabled,
                entitlements,
                entitlementsLoading
            )
        ).toBe(expected)
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

    it.each([403, 500])('denies access and reports the failure when the endpoint returns %s', async (status) => {
        const capture = jest.spyOn(toolbarPosthogJS, 'capture')
        const warn = jest.spyOn(toolbarLogger, 'warn')
        useMocks({
            get: {
                '/api/user/toolbar_entitlements': () => [status, {}],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadEntitlements()
        })
            .toDispatchActions(['loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: null })

        expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(false)
        expect(capture).toHaveBeenCalledWith(
            'toolbar api request',
            expect.objectContaining({ pathname: '/api/user/toolbar_entitlements', status })
        )
        expect(warn).toHaveBeenCalledWith('entitlements', expect.any(String), expect.objectContaining({ status }))
        jest.restoreAllMocks()
    })

    it('keeps an open heatmap disabled until access is confirmed and disables it after access is lost', async () => {
        jest.spyOn(toolbarPosthogJS, 'getFeatureFlag').mockReturnValue(true)
        const toolbar = toolbarLogic()
        toolbar.mount()
        const heatmap = heatmapToolbarMenuLogic()
        let finishRequest!: (value: unknown) => void
        const response = new Promise((resolve) => {
            finishRequest = resolve
        })
        useMocks({ get: { '/api/user/toolbar_entitlements': () => response } })

        logic.actions.loadEntitlements()
        toolbar.actions.setVisibleMenu('heatmap')
        expect(logic.values.entitlementsLoading).toBe(true)
        expect(isToolbarFeatureGated(AvailableFeature.TOOLBAR_HEATMAPS, 'toolbar-paid-heatmaps')).toBe(true)
        expect(heatmap.values.heatmapEnabled).toBe(false)

        await expectLogic(logic, () => {
            finishRequest({ entitlements: { toolbar_heatmaps: true } })
        }).toFinishAllListeners()
        expect(logic.values.entitlementsLoading).toBe(false)
        expect(heatmap.values.heatmapEnabled).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.loadEntitlements()
            expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(false)
            expect(heatmap.values.heatmapEnabled).toBe(false)
        }).toFinishAllListeners()
        expect(heatmap.values.heatmapEnabled).toBe(true)

        logic.actions.loadEntitlementsSuccess({ toolbar_heatmaps: false })
        expect(heatmap.values.heatmapEnabled).toBe(false)
        toolbar.unmount()
        jest.restoreAllMocks()
    })

    it.each([true, false])('gates unmounted entitlement logic only when rollout is %s', (rolloutEnabled) => {
        initKeaTests()
        jest.spyOn(toolbarPosthogJS, 'getFeatureFlag').mockReturnValue(rolloutEnabled)
        expect(isToolbarFeatureGated(AvailableFeature.TOOLBAR_HEATMAPS, 'toolbar-paid-heatmaps')).toBe(rolloutEnabled)
        jest.restoreAllMocks()
    })
})
