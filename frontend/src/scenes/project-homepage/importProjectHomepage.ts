import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

// The esbuild chunk map keys a lazy module by its first named export, so each name here must match its module's export.
export function importAiFirstHomepage(): Promise<typeof import('./ai-first/AiFirstHomepage')> {
    window.ESBUILD_LOAD_CHUNKS?.('AiFirstHomepage')
    return import('./ai-first/AiFirstHomepage')
}

export function importTodayHome(): Promise<typeof import('./today/TodayHome')> {
    window.ESBUILD_LOAD_CHUNKS?.('TodayHome')
    return import('./today/TodayHome')
}

// The boot prefetch runs before the app mounts featureFlagLogic, so it reads the flag from posthog-js.
function todayRailNavIsOn(): boolean {
    const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags
    return featureFlags
        ? !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
        : !!posthog.isFeatureEnabled(FEATURE_FLAGS.TODAY_RAIL_NAV, { send_event: false })
}

export function importProjectHomepage(): Promise<typeof import('./ProjectHomepage')> {
    const importContent = todayRailNavIsOn() ? importTodayHome : importAiFirstHomepage
    importContent().catch(() => {})
    return import('./ProjectHomepage')
}
