import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
})
