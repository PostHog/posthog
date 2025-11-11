import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { Scene } from '~/scenes/sceneTypes'
import { initKeaTests } from '~/test/init'

import { topBarSettingsButtonLogic } from './topBarSettingsButtonLogic'

const groupsScene = (): any => ({
    scene: { component: () => null, logic: null, settingSectionId: 'environment-customer-analytics' },
})
const personsScene = (): any => ({
    scene: { component: () => null, logic: null, settingSectionId: 'environment-product-analytics' },
})

const scenes: Record<string, () => any> = {
    [Scene.Groups]: groupsScene,
    [Scene.Persons]: personsScene,
}

describe('topBarSettingsButtonLogic', () => {
    describe('loadedSceneSettingsSectionId selector for environment-customer-analytics', () => {
        let logic: ReturnType<typeof topBarSettingsButtonLogic.build>
        let sceneLogicInstance: ReturnType<typeof sceneLogic.build>

        beforeEach(() => {
            initKeaTests()
            router.actions.push(urls.groups(0))
            sceneLogicInstance = sceneLogic({ scenes })
            sceneLogicInstance.mount()

            logic = topBarSettingsButtonLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            sceneLogicInstance?.unmount()
        })

        it('returns environment-customer-analytics when customer-analytics feature flag is enabled', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true,
            })

            await expectLogic(logic).toMatchValues({
                loadedSceneSettingsSectionId: 'environment-customer-analytics',
            })
        })

        it('returns undefined when customer-analytics feature flag is disabled for environment-customer-analytics', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: false,
            })

            await expectLogic(logic).toMatchValues({
                loadedSceneSettingsSectionId: undefined,
            })
        })
    })

    describe('loadedSceneSettingsSectionId selector for all settingSectionIds', () => {
        let logic: ReturnType<typeof topBarSettingsButtonLogic.build>
        let sceneLogicInstance: ReturnType<typeof sceneLogic.build>

        beforeEach(() => {
            initKeaTests()
            router.actions.push(urls.persons())
            sceneLogicInstance = sceneLogic({ scenes })
            sceneLogicInstance.mount()

            logic = topBarSettingsButtonLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            sceneLogicInstance?.unmount()
        })

        it('returns other setting section IDs regardless of CRM feature flag state', async () => {
            router.actions.push(urls.persons())
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CRM_ITERATION_ONE]: false,
            })

            await expectLogic(logic).toMatchValues({
                loadedSceneSettingsSectionId: 'environment-product-analytics',
            })

            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.CRM_ITERATION_ONE]: true,
            })

            await expectLogic(logic).toMatchValues({
                loadedSceneSettingsSectionId: 'environment-product-analytics',
            })
        })
    })
})
