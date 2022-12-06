import { sceneLogic } from './sceneLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic, partial, truth } from 'kea-test-utils'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { kea, path } from 'kea'

import type { logicType } from './sceneLogic.testType'

export const Component = (): JSX.Element => <div />
export const logic = kea<logicType>([path(['scenes', 'sceneLogic', 'test'])])
const sceneImport = (): any => ({ scene: { component: Component, logic: logic } })

const testScenes: Record<string, () => any> = {
    [Scene.Annotations]: sceneImport,
    [Scene.MySettings]: sceneImport,
}

describe('sceneLogic', () => {
    let logic: ReturnType<typeof sceneLogic.build>

    beforeEach(async () => {
        initKeaTests()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        router.actions.push(urls.annotations())
        logic = sceneLogic({ scenes: testScenes })
        logic.mount()
    })

    it('has preloaded some scenes', async () => {
        const preloadedScenes = [Scene.Error404, Scene.ErrorNetwork, Scene.ErrorProjectUnavailable]
        await expectLogic(logic).toMatchValues({
            loadedScenes: truth(
                (obj: Record<string, any>) =>
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
