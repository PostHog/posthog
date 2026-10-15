import posthog from 'posthog-js'
import { useEffect } from 'react'

import { bootMilestoneTimings, markBootMilestone } from 'lib/utils/bootMarks'

let bootTimingReported = false

/**
 * Sends the boot milestones once per page load, so field data shows which boot step is slow.
 * App renders it inside the scene subtree, so for logged-in users its effect waits for AuthenticatedShell to load.
 */
export function BootTimingReporter({ sceneId, loggedIn }: { sceneId: string | null; loggedIn: boolean }): null {
    useEffect(() => {
        if (bootTimingReported) {
            return
        }
        bootTimingReported = true
        markBootMilestone('first-scene-rendered')
        const timings = bootMilestoneTimings()
        posthog.capture('app boot timing', {
            scene: sceneId,
            logged_in: loggedIn,
            entry_start_ms: timings['entry-start'],
            app_modules_loaded_ms: timings['app-modules-loaded'],
            render_start_ms: timings['render-start'],
            app_booted_ms: timings['app-booted'],
            first_scene_rendered_ms: timings['first-scene-rendered'],
        })
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps
    return null
}
