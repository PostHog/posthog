import posthog from 'posthog-js'

import { sceneLogic } from 'scenes/sceneLogic'

/**
 * Central instrumentation for the SceneMenuBar experiment (`SCENE_MENU_BAR` flag). Capturing
 * here means every scene that adopts the bar reports engagement without per-scene wiring.
 * Scene id is read off `sceneLogic` without subscribing so capture never triggers a re-render.
 *
 * Pinned: the event names and property names are wire strings. Dashboards depend on them, so do not rename them.
 */
export function captureSceneMenuBar(event: string, properties: Record<string, unknown> = {}): void {
    posthog.capture(event, {
        scene: sceneLogic.findMounted()?.values.activeSceneId ?? null,
        ...properties,
    })
}
