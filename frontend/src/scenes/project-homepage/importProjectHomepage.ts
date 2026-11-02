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

export function importProjectHomepage(): Promise<typeof import('./ProjectHomepage')> {
    const importContent = featureFlagLogic.values.featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
        ? importTodayHome
        : importAiFirstHomepage
    // ProjectHomepage imports the content again and handles a failure there.
    importContent().catch(() => {})
    return import('./ProjectHomepage')
}
