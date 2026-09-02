/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { githubBranchSearchLogic } from './githubBranchSearchLogic'

describe('githubBranchSearchLogic', () => {
    let logic: ReturnType<typeof githubBranchSearchLogic.build>

    afterEach(() => logic?.unmount())

    it('surfaces a branch loading failure', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/github_branches/': () => [500, { detail: 'Unavailable' }],
            },
        })
        initKeaTests()
        logic = githubBranchSearchLogic({ integrationId: 1, repo: 'acme/web' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.refresh()).toFinishAllListeners()

        expect(logic.values.loading).toBe(false)
        expect(logic.values.error).toBe("Couldn't load branches. Refresh and try again.")
    })
})
