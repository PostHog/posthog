import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { supportLogic } from './supportLogic'
import * as SupportModal from './SupportModal'
import { supportRouterLogic } from './supportRouterLogic'

// supportLogic and SupportModal import each other, so spy on the live module export to intercept the call.
const openSupportModal = jest.spyOn(SupportModal, 'openSupportModal').mockImplementation(() => {})

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
        update: jest.fn(),
    },
}))

const sceneImport = (): any => ({ scene: { component: () => null } })

// Login is plain-layout (no side panel); event definitions is full-layout (side panel available).
const testScenes: Record<string, () => any> = {
    [Scene.Login]: sceneImport,
    [Scene.DataManagement]: sceneImport,
}

describe('supportRouterLogic', () => {
    beforeEach(async () => {
        localStorage.clear()
        // Logged out, so the onlyUnauthenticated Login scene renders instead of redirecting away.
        window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
        initKeaTests()
        ;(api.get as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        ;(api.update as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        sidePanelStateLogic.mount()
        supportLogic.mount()
        openSupportModal.mockClear()
    })

    afterEach(() => {
        supportRouterLogic.findMounted()?.unmount()
        delete window.POSTHOG_APP_CONTEXT
    })

    // The reported bug: on a cold load the scene chunk hasn't resolved, so the layout is unknown and the
    // router used to send every plain-layout scene to the side panel, which renders no support form. The
    // modal (openSupportModal) is the only surface with a working form on a plain-layout scene.
    it('waits for a plain-layout scene to settle, then opens the modal not the side panel', async () => {
        router.actions.push(urls.login(), {}, { panel: 'support' })
        // Scene chunk load is async, so sceneId is still null when the router mounts and fires.
        sceneLogic.build({ scenes: testScenes }).mount()
        supportRouterLogic.mount()

        // Deferred: no surface opens while the scene is still loading.
        expect(openSupportModal).not.toHaveBeenCalled()

        await expectLogic(supportLogic).toDispatchActions(['openSupportForm'])

        expect(openSupportModal).toHaveBeenCalledTimes(1)
    })

    // The other half of the fix must not over-correct: a full-layout scene still opens the side panel,
    // so the modal must not open there.
    it('opens the side panel on a full-layout scene', async () => {
        router.actions.push(urls.eventDefinitions(), {}, { panel: 'support' })
        sceneLogic.build({ scenes: testScenes }).mount()
        supportRouterLogic.mount()

        await expectLogic(supportLogic).toDispatchActions(['openSupportForm'])

        expect(openSupportModal).not.toHaveBeenCalled()
    })
})
