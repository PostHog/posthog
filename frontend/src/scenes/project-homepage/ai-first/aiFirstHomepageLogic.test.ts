import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'

describe('aiFirstHomepageLogic', () => {
    let logic: ReturnType<typeof aiFirstHomepageLogic.build>

    useMocks({
        get: {
            '/api/environments/:team_id/dashboards/': { results: [], count: 0 },
            '/api/environments/:team_id/conversations/': { results: [], count: 0 },
        },
    })

    beforeEach(() => {
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] })
        jest.spyOn(api.fileSystemLogView, 'list').mockResolvedValue([])

        initKeaTests()
        logic = aiFirstHomepageLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('urlToAction', () => {
        // kea-router's decodeParams coerces numeric-looking strings to Numbers, plus
        // "true"/"false" to booleans. We must always end up with a string in `query`
        // — otherwise downstream `query.trim()` calls in Search.Root crash.
        it.each([
            ['numeric-looking string', '12345'],
            ['zero', '0'],
            ['decimal', '1.5'],
            ['negative number', '-42'],
            ['boolean-like true', 'true'],
            ['boolean-like false', 'false'],
            ['plain string', 'abc'],
        ])('coerces ?q=%s param to a string in the query reducer', async (_, q) => {
            router.actions.push('/home', { mode: 'search', q })
            await expectLogic(logic).toFinishAllListeners()
            expect(typeof logic.values.query).toBe('string')
            expect(logic.values.query).toBe(q)
        })

        it('treats a missing q param as an empty string', async () => {
            router.actions.push('/home', { mode: 'idle' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.query).toBe('')
        })
    })
})
