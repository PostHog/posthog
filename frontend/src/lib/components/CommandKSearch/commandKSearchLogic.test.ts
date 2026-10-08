import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { commandKSearchLogic } from './commandKSearchLogic'

const EMPTY_PAGE = { results: [], count: 0 }

describe('commandKSearchLogic', () => {
    let logic: ReturnType<typeof commandKSearchLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': EMPTY_PAGE,
                '/api/environments/:team_id/file_system/': EMPTY_PAGE,
                '/api/environments/:team_id/file_system/log_view/': [],
                '/api/environments/:team_id/search/': { results: [], counts: {} },
                '/api/environments/:team_id/persons/': EMPTY_PAGE,
            },
        })
        initKeaTests()
        logic = commandKSearchLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    test('offers PostHog AI for free text, with no empty state', async () => {
        logic.actions.inputChanged('revenue', 7, false)
        await expectLogic(logic).toDispatchActions(['remoteLoaded']).toMatchValues({
            askAiQuestion: 'revenue',
            tabAsksAi: true,
            showNoResults: false,
        })
        expect(logic.values.sections.map((section) => section.key)).toContain('ask-ai')
    })

    test('a filter with no matches hides PostHog AI and shows the empty state until cleared', async () => {
        logic.actions.inputChanged('is:dashboard revenue', 20, true)
        await expectLogic(logic).toDispatchActions(['remoteLoaded']).toMatchValues({
            askAiQuestion: '',
            tabAsksAi: false,
            sections: [],
            showNoResults: true,
        })

        logic.actions.clearQuery('no-results')
        expect(logic.values).toMatchObject({ chips: [], text: '', showNoResults: false })
    })
})
