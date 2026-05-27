import { expectLogic } from 'kea-test-utils'

import { maxLogic } from 'scenes/max/maxLogic'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'

describe('aiFirstHomepageLogic', () => {
    let logic: ReturnType<typeof aiFirstHomepageLogic.build>
    let homepageMaxLogic: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/dashboards/': { results: [] },
                '/api/projects/:team_id/file_system/': { results: [] },
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
            },
        })
        initKeaTests()
        homepageMaxLogic = maxLogic({ panelId: HOMEPAGE_TAB_ID })
        homepageMaxLogic.mount()
        logic = aiFirstHomepageLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        if (homepageMaxLogic?.isMounted()) {
            homepageMaxLogic.actions.startNewConversation()
        }
        homepageMaxLogic?.unmount()
    })

    it('starts the thread when a question is submitted in AI mode', async () => {
        await expectLogic(logic, () => {
            logic.actions.setQuery('What are my top events?')
            logic.actions.submitQuery('ai')
        }).toMatchValues({
            threadStarted: true,
        })
    })

    it('starts the thread when a slash command is sent after entering AI mode via the / trigger', async () => {
        // Typing "/" on the homepage enters AI mode without submitting a query (e.g. to run /init).
        await expectLogic(logic, () => {
            logic.actions.enterAiMode('/')
        }).toMatchValues({
            mode: 'ai',
            // No query was submitted yet, so the thread hasn't started.
            threadStarted: false,
        })

        // Submitting the slash command goes through Max's askMax (on the homepage tab), not submitQuery.
        await expectLogic(logic, () => {
            homepageMaxLogic.actions.askMax('/init')
        }).toMatchValues({
            threadStarted: true,
        })
    })

    it('resets threadStarted when (re-)entering AI mode via a trigger', async () => {
        // A previously-sent message leaves the thread flag set.
        await expectLogic(logic, () => {
            homepageMaxLogic.actions.askMax('/init')
        }).toMatchValues({
            threadStarted: true,
        })

        // (Re-)entering AI mode via the "/" or "@" trigger opens command mode without sending, so the
        // thread flag must reset — a stale flag would otherwise flash an empty thread.
        await expectLogic(logic, () => {
            logic.actions.enterAiMode('@')
        }).toMatchValues({
            threadStarted: false,
        })
    })
})
