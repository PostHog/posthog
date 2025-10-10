import type { SdkType, SdkVersionInfo } from './types'

/**
 * Backend detection format from team SDK detection endpoint
 */
export type TeamSdkDetection = {
    type: SdkType
    version: string
    count: number
    lastSeen: string
}

/**
 * Defines how to generate map keys for each SDK type.
 * Web SDK uses short form, others use prefixed form.
 */
export const SDK_KEY_FORMATS: Record<SdkType, (version: string) => string> = {
    web: (version) => `web-${version}`,
    python: (version) => `posthog-python-${version}`,
    node: (version) => `posthog-node-${version}`,
    'react-native': (version) => `posthog-react-native-${version}`,
    flutter: (version) => `posthog-flutter-${version}`,
    ios: (version) => `posthog-ios-${version}`,
    android: (version) => `posthog-android-${version}`,
    go: (version) => `posthog-go-${version}`,
    php: (version) => `posthog-php-${version}`,
    ruby: (version) => `posthog-ruby-${version}`,
    elixir: (version) => `posthog-elixir-${version}`,
    dotnet: (version) => `posthog-dotnet-${version}`,
    other: (version) => `other-${version}`,
}

/**
 * SDK display names for logging
 */
const SDK_DISPLAY_NAMES: Record<SdkType, string> = {
    web: 'Web',
    python: 'Python',
    node: 'Node.js',
    'react-native': 'React Native',
    flutter: 'Flutter',
    ios: 'iOS',
    android: 'Android',
    go: 'Go',
    php: 'PHP',
    ruby: 'Ruby',
    elixir: 'Elixir',
    dotnet: '.NET',
    other: 'Other',
}

/**
 * Process SDK detections for a specific SDK type from backend data.
 * Converts backend detection format to frontend SdkVersionInfo format.
 */
export function processSdkDetections(
    detections: TeamSdkDetection[],
    sdkType: SdkType,
    getKey: (version: string) => string,
    debugMode = false
): Record<string, SdkVersionInfo> {
    const filtered = detections.filter((d) => d.type === sdkType)

    if (debugMode && filtered.length > 0) {
    }

    const result: Record<string, SdkVersionInfo> = {}

    filtered.forEach((detection) => {
        const key = getKey(detection.version)

        result[key] = {
            type: sdkType,
            version: detection.version,
            count: detection.count,
            isOutdated: false, // Will be updated by async version check
            lastSeenTimestamp: detection.lastSeen,
        }
    })

    return result
}

/**
 * Process all SDK detections from backend data.
 * Returns a complete map of all detected SDK versions.
 */
export function processAllSdkDetections(
    detections: TeamSdkDetection[],
    debugMode = false
): Record<string, SdkVersionInfo> {
    const result: Record<string, SdkVersionInfo> = {}

    // Process each SDK type
    for (const [sdkType, getKey] of Object.entries(SDK_KEY_FORMATS)) {
        const sdkDetections = processSdkDetections(detections, sdkType as SdkType, getKey, debugMode)
        Object.assign(result, sdkDetections)
    }

    return result
}
