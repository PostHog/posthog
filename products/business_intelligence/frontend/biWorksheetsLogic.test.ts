import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { biWorksheetsLogic } from './biWorksheetsLogic'

describe('worksheet library', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/insights/': { count: 0, results: [] } } })
        initKeaTests()
    })

    it.each([
        ['/bi?open_insight=worksheet1', '/bi/worksheet1'],
        ['/bi#q=', '/bi/new'],
    ])('preserves legacy worksheet links: %s', async (url, path) => {
        router.actions.push(url)
        const logic = biWorksheetsLogic()
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.location.pathname).toBe(`/project/997${path}`)
            expect(logic.values.worksheets).toBeNull()
        } finally {
            logic.unmount()
        }
    })
})
