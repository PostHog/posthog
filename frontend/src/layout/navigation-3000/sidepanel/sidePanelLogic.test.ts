import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
        update: jest.fn(),
        create: jest.fn(),
        recordings: {
            listPlaylists: jest.fn(),
        },
    },
}))

const sceneImport = (): any => ({ scene: { component: () => null } })

const testScenes: Record<string, () => any> = {
    [Scene.DataManagement]: sceneImport,
    [Scene.Settings]: sceneImport,
}

describe('sidePanelLogic', () => {
    let logic: ReturnType<typeof sidePanelLogic.build>

    const navigate = async (url: string, hashParams?: Record<string, any>): Promise<void> => {
        router.actions.push(url, {}, hashParams)
        await expectLogic(sceneLogic).toDispatchActions(['setScene'])
    }

    beforeEach(async () => {
        initKeaTests()
        ;(api.get as jest.Mock).mockResolvedValue({
            tabs: [],
            homepage: null,
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        ;(api.update as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        ;(api.recordings.listPlaylists as jest.Mock).mockResolvedValue({ results: [], count: 0, filters: null })
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        sceneLogic.build({ scenes: testScenes }).mount()
        logic = sidePanelLogic.build()
        logic.mount()
        await navigate(urls.eventDefinitions())
    })

    it('closes a context-bound tab when navigating to a different scene', async () => {
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Activity)
        await navigate(urls.settings('user'))
        await expectLogic(sidePanelStateLogic).toMatchValues({ sidePanelOpen: false })
    })

    it.each([SidePanelTab.Max, SidePanelTab.Support, SidePanelTab.Notebooks])(
        'keeps the %s tab open when navigating to a different scene',
        async (tab) => {
            sidePanelStateLogic.actions.openSidePanel(tab)
            await navigate(urls.settings('user'))
            await expectLogic(sidePanelStateLogic).toMatchValues({ sidePanelOpen: true, selectedTab: tab })
        }
    )

    it('closes a context-bound tab when navigating between settings sections', async () => {
        await navigate(urls.settings('user'))
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Discussion)
        await navigate(urls.settings('project'))
        await expectLogic(sidePanelStateLogic).toMatchValues({ sidePanelOpen: false })
    })

    it('keeps a persisted tab open when navigating between settings sections', async () => {
        await navigate(urls.settings('user'))
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
        await navigate(urls.settings('project'))
        await expectLogic(sidePanelStateLogic).toMatchValues({ sidePanelOpen: true, selectedTab: SidePanelTab.Max })
    })

    it('stays open across search param changes within the same settings section', async () => {
        await navigate(urls.settings('user'))
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Discussion)
        router.actions.push(urls.settings('user'), { access_tab: 'members' })
        await expectLogic(sidePanelStateLogic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Discussion,
        })
    })

    it('does not close a panel deep-linked via #panel= on the destination URL', async () => {
        await navigate(urls.settings('user'), { panel: 'discussion' })
        await expectLogic(sidePanelStateLogic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Discussion,
        })
    })
})
