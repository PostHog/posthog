import { OrganizationMembershipLevel } from 'lib/constants'
import { getAppContext } from 'lib/utils/getAppContext'
import { Scene } from 'scenes/sceneTypes'

/** The project scenes a guest can open. Every other project scene shows access denied, and its nav item is disabled. */
export const GUEST_SCENES: ReadonlySet<string> = new Set<string>([
    Scene.Dashboards,
    Scene.Dashboard,
    Scene.Insight,
    Scene.SavedInsights,
    Scene.Notebooks,
    Scene.Notebook,
    Scene.Settings,
])

export function isGuestUser(): boolean {
    return getAppContext()?.current_user?.organization?.membership_level === OrganizationMembershipLevel.Guest
}

/**
 * Whether a guest may not open this scene. Pass the scene's `projectBased` setting: scenes outside a project, such as
 * login and the error pages, stay open.
 */
export function isSceneDeniedToGuest(sceneId: string | null | undefined, projectBased: boolean | undefined): boolean {
    if (!sceneId || projectBased !== true || !isGuestUser()) {
        return false
    }
    return !GUEST_SCENES.has(sceneId)
}
