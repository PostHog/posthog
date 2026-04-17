import { Scene } from 'scenes/sceneTypes'

export const GUEST_ALLOWED_SCENES: ReadonlySet<Scene> = new Set([
    Scene.Dashboard,
    Scene.Insight,
    Scene.Notebook,
    Scene.Settings,
    Scene.GuestLanding,
    Scene.GuestNotFound,
])
