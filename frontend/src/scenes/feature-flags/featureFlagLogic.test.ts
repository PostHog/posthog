import { BuiltLogic } from 'kea'
import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial, truth } from 'kea-test-utils'
import { initKeaTestLogic, initKeaTests } from '~/test/init'
import { featureFlagLogic } from './featureFlagLogic'
import { router } from 'kea-router'
import { featureFlagLogicType } from './featureFlagLogicType'
import { featureFlagsLogic } from './featureFlagsLogic'
import { teamLogic } from 'scenes/teamLogic'

jest.mock('lib/api')

describe('featureFlagLogic', () => {
    let logic: BuiltLogic<featureFlagLogicType>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/feature_flags/`) {
            return {"results": [{
                id: 1,
                key: 'test'
            }]}
        }
        if (pathname === `api/projects/${MOCK_TEAM_ID}/feature_flags/1`) {
            return {id: 1, key: 'test'}
        }
        return defaultAPIMocks(url)
    })
    beforeEach(async () => {
        initKeaTests()

        teamLogic.mount()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagsLogic.mount()
        await expectLogic(featureFlagsLogic).toDispatchActions(['loadFeatureFlagsSuccess'])
        
    })
    
    it('redirects from a url with the key to ID', async () => {
        router.actions.push('/feature_flags/test')
        featureFlagLogic.mount()
        
        await expectLogic(router).toDispatchActions(['push', 'locationChanged',])
        .toMatchValues({location: partial({pathname: "/feature_flags/2"})})

    })

})
