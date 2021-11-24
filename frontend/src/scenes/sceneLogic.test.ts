import { sceneLogic } from './sceneLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic, partial, truth } from 'kea-test-utils'
import { LoadedScene, Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { defaultAPIMocks, MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { appScenes } from 'scenes/appScenes'

jest.mock('lib/api')

describe('sceneLogic', () => {
    let logic: ReturnType<typeof sceneLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/`) {
            return { result: null, next: null }
        }
        return defaultAPIMocks(url)
    })

    beforeEach(async () => {
        initKeaTests()
        teamLogic.mount()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        router.actions.push(urls.annotations())
        logic = sceneLogic({ scenes: appScenes })
        logic.mount()
    })

    it('has preloaded some scenes', async () => {
        const preloadedScenes = [Scene.Error404, Scene.ErrorNetwork, Scene.ErrorProjectUnavailable]
        await expectLogic(logic).toMatchValues({
            loadedScenes: truth(
                (obj: Record<string, LoadedScene>) =>
                    Object.keys(obj).filter((key) => preloadedScenes.includes(key as Scene)).length === 3
            ),
        })
    })

    it('changing URL runs openScene, loadScene and setScene', async () => {
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            scene: Scene.Annotations,
        })
        router.actions.push(urls.mySettings())
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            scene: Scene.MySettings,
        })
    })

    it('persists the loaded scenes', async () => {
        const expectedAnnotation = partial({
            name: Scene.Annotations,
            component: expect.any(Function),
            logic: expect.any(Function),
            sceneParams: { hashParams: {}, params: {}, searchParams: {} },
            lastTouch: expect.any(Number),
        })

        const expectedMySettings = partial({
            name: Scene.MySettings,
            component: expect.any(Function),
            sceneParams: { hashParams: {}, params: {}, searchParams: {} },
            lastTouch: expect.any(Number),
        })

        await expectLogic(logic)
            .delay(1)
            .toMatchValues({
                loadedScenes: partial({
                    [Scene.Annotations]: expectedAnnotation,
                }),
            })
        router.actions.push(urls.mySettings())
        await expectLogic(logic)
            .delay(1)
            .toMatchValues({
                loadedScenes: partial({
                    [Scene.Annotations]: expectedAnnotation,
                    [Scene.MySettings]: expectedMySettings,
                }),
            })
    })
})
