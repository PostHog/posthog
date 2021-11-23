import { initKeaTests } from '~/test/init'
import { insightRouterLogic } from 'scenes/insights/insightRouterLogic'
import { router } from 'kea-router'
import { defaultAPIMocks, MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
jest.mock('lib/api')

describe('insightRouterLogic', () => {
    let logic: ReturnType<typeof insightRouterLogic.build>

    mockAPI(async (url) => {
        const { pathname, data } = url
        console.log(pathname)
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights`) {
            return {
                ...data,
                result: ['result from api'],
                id: 42,
                filters: data?.filters || {},
            }
        }
        return defaultAPIMocks(url)
    })

    beforeEach(() => {
        initKeaTests()
        logic = insightRouterLogic()
        logic.mount()
    })

    it('redirects when opening /insight/new', async () => {
        router.actions.push('/insights/new')
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({ pathname: '/insights' }),
                searchParams: partial({ insight: 'TRENDS' }),
                hashParams: partial({ edit: true, fromItem: 42 }),
            })

        router.actions.push('/insights/new?insight=FUNNELS')
        await expectLogic(router)
            .delay(1)
            .toMatchValues({
                location: partial({ pathname: '/insights' }),
                searchParams: partial({ insight: 'FUNNELS' }),
                hashParams: partial({ edit: true, fromItem: 42 }),
            })
    })
})
