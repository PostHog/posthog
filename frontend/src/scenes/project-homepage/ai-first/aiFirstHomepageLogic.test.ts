import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { DashboardBasicType } from '~/types'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'

describe('aiFirstHomepageLogic', () => {
    let logic: ReturnType<typeof aiFirstHomepageLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/conversations/': { results: [] },
                '/api/projects/:team_id/dashboards/': { results: [] },
                '/api/projects/:team_id/file_system/': { results: [] },
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        sidePanelStateLogic.mount()
        logic = aiFirstHomepageLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        sidePanelStateLogic.unmount()
    })

    // Regression guard: on the PostHog AI homepage, a `#panel=max:<prompt>` link should prefill the
    // full-scene chat, not stack a redundant Max side panel on top of it. Without interception the
    // side panel opens (via sidePanelStateLogic's `*` handler) and the prompt never reaches the
    // homepage composer.
    it('consumes #panel=max:<prompt> into the full-scene chat instead of the side panel', async () => {
        // The one navigation drives both logics: sidePanelStateLogic opens the Max panel, then the
        // homepage handler closes it again and enters AI mode with the prompt prefilled.
        router.actions.push(urls.projectHomepage(), {}, { panel: 'max:what is my dau' })
        await expectLogic(logic).delay(1).toMatchValues({ mode: 'ai' })

        expect(maxLogic({ panelId: HOMEPAGE_TAB_ID }).values.question).toEqual('what is my dau')
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    // The homepage chat only drives the legacy runtime. Without the handoff, a prompt submitted by a
    // user on the new PostHog AI surface starts a LangGraph conversation that surface never renders,
    // so the submit looks like it did nothing.
    it.each([
        ['legacy view', false, '/project/997/home', 'ai'],
        ['new view', true, '/project/997/ai', 'idle'],
    ])('submitting a prompt on the %s', async (_case, sandboxFlagOn, expectedPathname, expectedMode) => {
        if (sandboxFlagOn) {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE], {
                [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
            })
        }
        router.actions.push(urls.projectHomepage())

        logic.actions.setQuery('what is my dau')
        logic.actions.submitQuery('ai')
        await expectLogic(logic).delay(1)

        expect(router.values.location.pathname).toEqual(expectedPathname)
        expect(logic.values.mode).toEqual(expectedMode)
        // The prompt rides along as `ask`, which the new surface's composer seeds and submits.
        expect(router.values.searchParams.ask).toEqual(sandboxFlagOn ? 'what is my dau' : undefined)
    })

    it('shows up to eight pinned dashboards, recents, and starred items', () => {
        const createFileSystemEntries = (prefix: string): FileSystemEntry[] =>
            Array.from({ length: 9 }, (_, index) => ({
                id: `${prefix}-${index}`,
                path: `${prefix} ${index}`,
                type: 'insight',
            }))

        dashboardsModel.actions.loadDashboardsSuccess({
            count: 9,
            next: null,
            previous: null,
            results: Array.from({ length: 9 }, (_, index) => ({
                id: index,
                name: `Dashboard ${index}`,
                pinned: true,
            })) as DashboardBasicType[],
        })
        recentItemsModel.actions.loadRecentsSuccess(createFileSystemEntries('Recent'))
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            ...createFileSystemEntries('Starred'),
            { id: 'starred-folder', path: 'Starred folder', type: 'folder' },
        ])

        expect(logic.values.gridItems.filter((item) => item.kind === 'dashboard')).toHaveLength(8)
        expect(logic.values.gridItems.filter((item) => item.kind === 'recent')).toHaveLength(8)
        expect(logic.values.gridItems.filter((item) => item.kind === 'starred')).toHaveLength(8)
    })
})
