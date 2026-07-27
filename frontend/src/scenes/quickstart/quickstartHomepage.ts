import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { emptySceneParams } from 'scenes/scenes'
import { Scene, SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function quickstartHomepageTab(): SceneTab {
    return {
        id: 'homepage-quickstart',
        pathname: urls.quickstart(),
        search: '',
        hash: '',
        title: 'Quickstart',
        // 'early_access_feature' renders IconRocket, matching the Quickstart nav item
        iconType: 'early_access_feature',
        sceneId: Scene.Quickstart,
        sceneKey: 'quickstart',
        sceneParams: emptySceneParams,
    }
}

/**
 * Makes Quickstart the user's default screen when they complete onboarding for the first
 * time, so the Home button lands there until they pick something else in the Configure
 * homepage modal. Users who already onboarded a product or configured a homepage keep
 * whatever they have.
 */
export function setQuickstartAsDefaultHomepageOnce(
    hasCompletedOnboardingFor: Record<string, boolean> | undefined
): void {
    if (featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.QUICKSTART_HOMEPAGE] !== 'test') {
        return
    }
    const scene = sceneLogic.findMounted()
    if (!scene || scene.values.homepage) {
        return
    }
    if (Object.values(hasCompletedOnboardingFor ?? {}).some(Boolean)) {
        return
    }
    scene.actions.setHomepage(quickstartHomepageTab())
}
