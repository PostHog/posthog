import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { sceneAgentPanelLogic } from './sceneAgentPanelLogic'
import { maxMocks } from './testUtils'

describe('sceneAgentPanelLogic', () => {
    let logic: ReturnType<typeof sceneAgentPanelLogic.build>

    const setFlags = (flags: string[]): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    const allFlags = [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE]

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        localStorage.clear()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        logic = sceneAgentPanelLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('opens the PostHog AI panel when a scene registers and all gates pass', async () => {
        setFlags(allFlags)

        await expectLogic(logic, () => {
            logic.actions.sceneEntered('workflow')
        }).toFinishAllListeners()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
    })

    // Auto-open is the most intrusive behavior here: any gate regression leaks a self-opening panel
    // to users who never opted in (flag off), users on the legacy Max view (which has no attached-context
    // consumer), or clobbers a panel the user explicitly opened.
    it.each([
        {
            name: 'the auto-open flag is off',
            flags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE],
            setup: () => {},
        },
        {
            name: 'the sandbox flag is off (legacy Max view)',
            flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN],
            setup: () => {},
        },
        {
            name: 'another side panel tab is open',
            flags: allFlags,
            setup: () => sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Notebooks),
        },
        {
            name: 'the side panel is unavailable',
            flags: allFlags,
            setup: () => sidePanelStateLogic.actions.setSidePanelAvailable(false),
        },
    ])('does not open the panel when $name', async ({ flags, setup }) => {
        setFlags(flags)
        setup()
        const tabBefore = sidePanelStateLogic.values.selectedTab

        await expectLogic(logic, () => {
            logic.actions.sceneEntered('workflow')
        }).toFinishAllListeners()

        expect(sidePanelStateLogic.values.selectedTab).toBe(tabBefore)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(tabBefore !== null)
    })

    it('records a persisted dismissal when the user closes the panel, and stops auto-opening that scene', async () => {
        setFlags(allFlags)

        await expectLogic(logic, () => {
            logic.actions.sceneEntered('workflow')
        }).toFinishAllListeners()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)

        await expectLogic(logic, () => {
            sidePanelStateLogic.actions.closeSidePanel()
        }).toFinishAllListeners()
        expect(logic.values.autoOpenDismissedScenes).toEqual({ workflow: true })

        // Re-entering the scene (e.g. navigating away and back) must respect the dismissal.
        await expectLogic(logic, () => {
            logic.actions.sceneLeft('workflow')
            logic.actions.sceneEntered('workflow')
        }).toFinishAllListeners()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    // Closing an unrelated tab (e.g. docs panel the user peeked at) must not count as dismissing
    // the AI panel for the active scene.
    it('does not record a dismissal when a non-Max tab is closed', async () => {
        setFlags(allFlags)

        await expectLogic(logic, () => {
            logic.actions.sceneEntered('workflow')
        }).toFinishAllListeners()
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)

        await expectLogic(logic, () => {
            sidePanelStateLogic.actions.closeSidePanel(SidePanelTab.Support)
        }).toFinishAllListeners()

        expect(logic.values.autoOpenDismissedScenes).toEqual({})
    })

    it('does not record a dismissal for scenes registered after the panel was closed', async () => {
        setFlags(allFlags)

        await expectLogic(logic, () => {
            sidePanelStateLogic.actions.closeSidePanel()
        }).toFinishAllListeners()

        expect(logic.values.autoOpenDismissedScenes).toEqual({})

        await expectLogic(logic, () => {
            logic.actions.sceneEntered('workflow')
        }).toFinishAllListeners()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
    })
})
