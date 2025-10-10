/**
 * Shared type definitions for SDK Doctor
 *
 * This file contains all the core type definitions used across SDK Doctor components.
 * These types are extracted from sidePanelSdkDoctorLogic.tsx for better organization
 * and reusability.
 */

/**
 * Supported SDK types for version detection and health monitoring
 */
export type SdkType =
    | 'web'
    | 'ios'
    | 'android'
    | 'node'
    | 'python'
    | 'php'
    | 'ruby'
    | 'go'
    | 'flutter'
    | 'react-native'
    | 'dotnet'
    | 'elixir'
    | 'other'

/**
 * Comprehensive version information for a detected SDK
 *
 * Includes version outdatedness, release metadata, device context,
 * and error handling for unavailable SDK Doctor data.
 */
export type SdkVersionInfo = {
    type: SdkType
    version: string
    isOutdated: boolean
    count: number
    releasesAhead?: number
    latestVersion?: string

    // Age-based tracking
    releaseDate?: string // ISO date string when this version was released
    daysSinceRelease?: number // Calculated days since release
    isAgeOutdated?: boolean // True if >8 weeks old AND newer releases exist

    // Device context
    deviceContext?: 'mobile' | 'desktop' | 'mixed' // Based on detected usage patterns
    eventVolume?: 'low' | 'medium' | 'high' // Based on event count
    lastSeenTimestamp?: string // ISO timestamp of most recent event

    // Error handling
    error?: string // Error message when SDK Doctor is unavailable
}

/**
 * Configuration for device context detection and age-based thresholds
 *
 * Defines which SDKs are considered mobile vs desktop, and thresholds
 * for event volume classification and version age warnings.
 */
export type DeviceContextConfig = {
    mobileSDKs: SdkType[] // ['ios', 'android', 'flutter', 'react-native']
    desktopSDKs: SdkType[] // ['web', 'node', 'python', 'php', 'ruby', 'go', 'dotnet', 'elixir']
    volumeThresholds: {
        low: number // < 10 events
        medium: number // 10-50 events
        high: number // > 50 events
    }
    ageThresholds: {
        warnAfterWeeks: number // 8 weeks
        criticalAfterWeeks: number // 16 weeks
    }
}

/**
 * Overall health status for SDK version monitoring
 */
export type SdkHealthStatus = 'healthy' | 'warning' | 'critical'
