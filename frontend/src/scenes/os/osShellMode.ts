import type { SceneConfig } from 'scenes/sceneTypes'

import type { Navigation3000Mode } from '~/layout/navigation-3000/navigationLogic'

export interface OsShellHostInput {
    osShellEnabled: boolean
    framed: boolean
    sceneConfig: SceneConfig | null
    organizationUnavailable: boolean
}

/**
 * True when this page renders the OS shell and opens the scene in a window frame. The frame runs its
 * own copy of the app, so the page itself must not render the scene or mount its logic.
 */
export function osShellHostsPage({
    osShellEnabled,
    framed,
    sceneConfig,
    organizationUnavailable,
}: OsShellHostInput): boolean {
    // A framed page never renders the OS shell, so an OS window cannot open a second desktop.
    // Scenes that own the whole page (onboarding, an unavailable organization) keep their layout.
    return osShellEnabled && !framed && !organizationUnavailable && sceneConfig?.layout !== 'plain'
}

export function resolveOsShellMode(
    regularMode: Navigation3000Mode,
    { framed, ...hostInput }: OsShellHostInput
): Navigation3000Mode {
    if (framed) {
        return 'framed'
    }
    return osShellHostsPage({ framed, ...hostInput }) ? 'os' : regularMode
}
