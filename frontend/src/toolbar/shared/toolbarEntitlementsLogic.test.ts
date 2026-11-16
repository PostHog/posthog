import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { toolbarLogic } from '~/toolbar/shared/bar/toolbarLogic'
import { heatmapToolbarMenuLogic } from '~/toolbar/shared/elements/heatmapToolbarMenuLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import {
    ToolbarEntitlements,
    ToolbarFeatureGateStatus,
    isToolbarFeatureGated,
    toolbarEntitlementsLogic,
    toolbarFeatureGateStatus,
} from '~/toolbar/shared/toolbarEntitlementsLogic'
import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'
import { AvailableFeature } from '~/types'

// The team and project ids differ so that a request built from the wrong one misses the mock.
const TEAM_ID = 2
const PROJECT_ID = 1
const ENTITLEMENTS_URL = `/api/projects/${TEAM_ID}/toolbar/entitlements/`

describe('toolbarEntitlementsLogic', () => {
    let logic: ReturnType<typeof toolbarEntitlementsLogic.build>

    beforeEach(async () => {
        initKeaTests()
        toolbarPosthogJS.stopSessionRecording = jest.fn()
        useMocks({ get: { [ENTITLEMENTS_URL]: () => ({ entitlements: {} }) } })
        toolbarConfigLogic
            .build({ apiURL: 'http://localhost', accessToken: 'test-token', teamId: TEAM_ID, projectId: PROJECT_ID })
            .mount()
        logic = toolbarEntitlementsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEntitlementsSuccess'])
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

    it("loads the entitlement map for the session's team with the session's token", async () => {
        const requests: { teamId: unknown; authorization: string | null }[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/toolbar/entitlements/': ({ request, params }) => {
                    requests.push({ teamId: params.team_id, authorization: request.headers.get('Authorization') })
                    return { entitlements: { toolbar_heatmaps: true } }
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadEntitlements()
        })
            .toDispatchActions(['loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: { toolbar_heatmaps: true } })

        expect(requests).toEqual([{ teamId: String(TEAM_ID), authorization: 'Bearer test-token' }])
    })

    it.each([403, 500])('denies access and reports the failure when the endpoint returns %s', async (status) => {
        const capture = jest.spyOn(toolbarPosthogJS, 'capture')
        useMocks({ get: { [ENTITLEMENTS_URL]: () => [status, {}] } })

        await expectLogic(logic, () => {
            logic.actions.loadEntitlements()
        })
            .toDispatchActions(['loadEntitlementsSuccess'])
            .toMatchValues({ entitlements: null })

        expect(logic.values.isEntitled(AvailableFeature.TOOLBAR_HEATMAPS)).toBe(false)
        expect(capture).toHaveBeenCalledWith(
            'toolbar api request',
            expect.objectContaining({ pathname: ENTITLEMENTS_URL, status })
        )
        jest.restoreAllMocks()
    })

    it('gives up on a stalled request so the retry becomes reachable', async () => {
        const capture = jest.spyOn(toolbarPosthogJS, 'capture')
        jest.useFakeTimers()
        useMocks({ get: { [ENTITLEMENTS_URL]: () => new Promise(() => {}) } })

        logic.actions.loadEntitlements()
        expect(logic.values.entitlementsLoading).toBe(true)

        // Well past the request's own bound. Without one, the loader would stay pending and the
        // menu would keep showing the spinner, which has no retry.
        jest.advanceTimersByTime(10_000)
        jest.useRealTimers()
        await expectLogic(logic).toDispatchActions(['loadEntitlementsSuccess'])

        expect(logic.values.entitlementsLoading).toBe(false)
        expect(logic.values.entitlements).toBe(null)
        expect(capture).toHaveBeenCalledWith(
            'toolbar api request',
            expect.objectContaining({ pathname: ENTITLEMENTS_URL, status: 0 })
        )
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
        useMocks({ get: { [ENTITLEMENTS_URL]: () => response } })

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

    it('disables an open heatmap when the rollout flag arrives after the menu opened', async () => {
        let onFeatureFlags: (() => void) | undefined
        jest.spyOn(toolbarPosthogJS, 'onFeatureFlags').mockImplementation((callback: any) => {
            onFeatureFlags = callback
            return () => {}
        })
        // The internal posthog instance bootstraps with no flags, so the gate reads as off
        // until its own /flags response lands.
        const getFeatureFlag = jest.spyOn(toolbarPosthogJS, 'getFeatureFlag').mockReturnValue(undefined)
        logic.actions.loadEntitlementsSuccess({ toolbar_heatmaps: false })
        const toolbar = toolbarLogic()
        toolbar.mount()
        const heatmap = heatmapToolbarMenuLogic()

        toolbar.actions.setVisibleMenu('heatmap')
        expect(heatmap.values.heatmapEnabled).toBe(true)

        getFeatureFlag.mockReturnValue(true)
        await expectLogic(toolbar, () => {
            onFeatureFlags?.()
        }).toFinishAllListeners()

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
