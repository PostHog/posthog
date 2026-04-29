import { GUEST_ALLOWED_SCENES } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

describe('GUEST_ALLOWED_SCENES', () => {
    const guestOnlyFacingScenes: Scene[] = [
        Scene.Guest,
        Scene.Dashboard,
        Scene.Insight,
        Scene.Notebook,
        Scene.Login,
        Scene.Error404,
        Scene.ErrorAccessDenied,
        Scene.ErrorNetwork,
        Scene.ErrorProjectUnavailable,
    ]

    it.each(guestOnlyFacingScenes.map((scene) => [scene] as const))('allows %s for guests', (scene) => {
        expect(GUEST_ALLOWED_SCENES.has(scene)).toBe(true)
    })

    const blockedScenes: Scene[] = [
        Scene.FeatureFlags,
        Scene.Experiments,
        Scene.Cohorts,
        Scene.DataWarehouseSource,
        Scene.WebAnalytics,
        Scene.Replay,
        Scene.Surveys,
        Scene.ProjectHomepage,
        Scene.NewTab,
        Scene.Settings,
        Scene.Persons,
        Scene.SavedInsights,
        Scene.Dashboards,
    ]

    it.each(blockedScenes.map((scene) => [scene] as const))('blocks %s for guests', (scene) => {
        expect(GUEST_ALLOWED_SCENES.has(scene)).toBe(false)
    })
})
