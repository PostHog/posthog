import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { urls } from 'scenes/urls'
import { initKeaTestLogic } from '~/test/init'
import { InsightType } from '~/types'
import { experimentLogic } from './experimentLogic'

jest.mock('lib/api')

describe('experimentLogic', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights`) {
            return { short_id: 'a5qqECqP', filters: { insight: InsightType.FUNNELS } }
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: experimentLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    describe('when creating a new experiment', () => {
        it('creates an insight funnel and clears the new experiment form', async () => {
            router.actions.push(urls.experiment('new'))
            await expectLogic(logic)
                .toDispatchActions(['setExperimentFunnel'])
                .toMatchValues({
                    experimentFunnel: { short_id: 'a5qqECqP', filters: { insight: InsightType.FUNNELS } },
                })
        })
    })
})
