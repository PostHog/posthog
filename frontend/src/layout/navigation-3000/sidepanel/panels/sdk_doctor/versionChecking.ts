import posthog from 'posthog-js'

import type { SdkType, SdkVersionInfo } from './types'

/**
 * Updates SDK version info with async version checking results.
 * Calls checkVersionAgainstLatestAsync and merges results into SdkVersionInfo.
 *
 * This function extracts the repetitive pattern used across all SDKs in the listener
 * that processes SDK detections. It handles:
 * - Calling the async version check function
 * - Extracting all result fields
 * - Determining device context with proper type casting
 * - Error handling with graceful degradation
 * - Categorizing event volume
 * - Setting last seen timestamp
 *
 * @param info - Current SDK version info
 * @param checkVersionAgainstLatestAsync - Async function to check version (passed in to avoid circular imports)
 * @param determineDeviceContext - Function to determine device context
 * @param categorizeEventVolume - Function to categorize event volume
 * @param sdkName - Human-readable SDK name for logging (e.g., "Go", ".NET", "PHP")
 * @returns Updated SdkVersionInfo with version check results
 */
export async function updateSdkVersionInfo(
    info: SdkVersionInfo,
    checkVersionAgainstLatestAsync: (
        type: SdkType,
        version: string
    ) => Promise<{
        isOutdated: boolean
        releasesAhead?: number
        latestVersion?: string
        releaseDate?: string
        daysSinceRelease?: number
        isAgeOutdated?: boolean
        deviceContext?: 'mobile' | 'desktop' | 'mixed'
        error?: string
    }>,
    determineDeviceContext: (type: SdkType) => 'mobile' | 'desktop' | 'mixed',
    categorizeEventVolume: (count: number) => 'low' | 'medium' | 'high',
    sdkName: string
): Promise<SdkVersionInfo> {
    console.info(`[SDK Doctor] ${sdkName} SDK async check for version ${info.version}`)

    try {
        const versionCheckResult = await checkVersionAgainstLatestAsync(info.type, info.version)

        // Special error handling for .NET SDK pattern - handle errors early
        if (versionCheckResult.error) {
            console.warn(`[SDK Doctor] ${sdkName} SDK: Version check error:`, versionCheckResult.error)
            return {
                ...info,
                isOutdated: false,
                releasesAhead: 0,
                latestVersion: versionCheckResult.latestVersion,
                releaseDate: undefined,
                daysSinceRelease: undefined,
                isAgeOutdated: false,
                deviceContext: determineDeviceContext(info.type),
                eventVolume: categorizeEventVolume(info.count),
                lastSeenTimestamp: new Date().toISOString(),
                error: versionCheckResult.error,
            }
        }

        // Extract all result fields
        const { isOutdated, releasesAhead, latestVersion, releaseDate, daysSinceRelease, isAgeOutdated, error } =
            versionCheckResult

        // Determine device context with proper type casting
        // Check if deviceContext is in result and use it, otherwise determine from SDK type
        const deviceContext =
            'deviceContext' in versionCheckResult && versionCheckResult.deviceContext
                ? (versionCheckResult.deviceContext as 'mobile' | 'desktop' | 'mixed')
                : determineDeviceContext(info.type)

        // Return updated SDK version info
        return {
            ...info,
            isOutdated,
            releasesAhead,
            latestVersion,
            releaseDate,
            daysSinceRelease,
            isAgeOutdated,
            deviceContext,
            eventVolume: categorizeEventVolume(info.count),
            lastSeenTimestamp: new Date().toISOString(),
            error,
        }
    } catch (error) {
        console.warn(`[SDK Doctor] Error processing ${info.type} SDK ${info.version}:`, error)
        posthog.captureException(error)

        // Return info with error state - graceful degradation
        return {
            ...info,
            isOutdated: false,
            releasesAhead: 0,
            latestVersion: undefined,
            releaseDate: undefined,
            daysSinceRelease: undefined,
            isAgeOutdated: false,
            deviceContext: determineDeviceContext(info.type),
            eventVolume: categorizeEventVolume(info.count),
            lastSeenTimestamp: new Date().toISOString(),
            error: error instanceof Error ? error.message : 'Unknown error occurred',
        }
    }
}
