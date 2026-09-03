import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { userGithubIntegrationLogic } from './userGithubIntegrationLogic'

const SCOPE_CASES: [string, string, string[]][] = [
    ['a scope change refetches the repository list', 'all', ['12345:0', '12345:0']],
    ['an unchanged scope keeps the cached list', 'selected', ['12345:0']],
]

describe('userGithubIntegrationLogic', () => {
    let logic: ReturnType<typeof userGithubIntegrationLogic.build>
    let repoRequests: string[]

    beforeEach(async () => {
        repoRequests = []
        useMocks({
            get: {
                '/api/users/:uuid/integrations/github/:installationId/repos/': ({ params, request }) => {
                    const offset = new URL(request.url).searchParams.get('offset') ?? '0'
                    repoRequests.push(`${params.installationId}:${offset}`)
                    return [
                        200,
                        {
                            repositories: [{ id: 1, name: 'posthog', full_name: 'PostHog/posthog' }],
                            has_more: false,
                            total: 712,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = userGithubIntegrationLogic({ installationId: '12345', repositorySelection: 'selected' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    // The logic is keyed by installation id alone, so polling that flips repository_selection in place
    // has to refetch — otherwise the row keeps describing the previous scope.
    it.each(SCOPE_CASES)('%s', async (_, repositorySelection, expectedRequests) => {
        userGithubIntegrationLogic({ installationId: '12345', repositorySelection })
        await expectLogic(logic).toFinishAllListeners()

        expect(repoRequests).toEqual(expectedRequests)
        expect(logic.values.repositoriesTotal).toBe(712)
    })

    it('clears the cached total when a reload starts so a scope change cannot show a stale count', async () => {
        expect(logic.values.repositoriesTotal).toBe(712)

        // A reload (e.g. after repository_selection flips via polling) drops the stale total
        // immediately, before the refetch resolves.
        logic.actions.loadRepositories()
        expect(logic.values.repositoriesTotal).toBeNull()

        await expectLogic(logic).toFinishAllListeners()
    })
})
