import { kea, path } from 'kea'
import { router } from 'kea-router'
import { expectLogic, partial, truth } from 'kea-test-utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { sceneLogic } from './sceneLogic'
import type { logicType } from './sceneLogic.testType'

export const Component = (): JSX.Element => <div />
export const logic = kea<logicType>([path(['scenes', 'sceneLogic', 'test'])])
const sceneImport = (): any => ({ scene: { component: Component, logic: logic } })

const testScenes: Record<string, () => any> = {
    [Scene.DataManagement]: sceneImport,
    [Scene.Settings]: sceneImport,
}

describe('sceneLogic', () => {
    let logic: ReturnType<typeof sceneLogic.build>

    beforeEach(async () => {
        initKeaTests()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        router.actions.push(urls.eventDefinitions())
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
            scene: Scene.DataManagement,
        })
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            scene: Scene.Settings,
        })
    })

    it('persists the loaded scenes', async () => {
        const expectedAnnotation = partial({
            id: Scene.DataManagement,
            component: expect.any(Function),
            logic: expect.any(Function),
            sceneParams: { hashParams: {}, params: {}, searchParams: {} },
            lastTouch: expect.any(Number),
        })

        const expectedSettings = partial({
            id: Scene.Settings,
            component: expect.any(Function),
            sceneParams: {
                hashParams: {},
                params: {
                    section: 'user',
                },
                searchParams: {},
            },
            logic: expect.any(Function),
            lastTouch: expect.any(Number),
        })

        await expectLogic(logic).delay(1)

        expect(logic.values.loadedScenes).toMatchObject({
            [Scene.DataManagement]: expectedAnnotation,
        })
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).delay(1)

        expect(logic.values.loadedScenes).toMatchObject({
            [Scene.DataManagement]: expectedAnnotation,
            [Scene.Settings]: expectedSettings,
        })
    })
})
