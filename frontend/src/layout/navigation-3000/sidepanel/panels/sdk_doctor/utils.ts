/**
 * Shared utility functions for SDK Doctor
 *
 * This file contains utility functions and configuration constants used across
 * SDK Doctor components. These are extracted from sidePanelSdkDoctorLogic.tsx
 * for better organization and reusability.
 */
import type { DeviceContextConfig, SdkType } from './types'

/**
 * Configuration for device context detection and age-based thresholds
 */
export const DEVICE_CONTEXT_CONFIG: DeviceContextConfig = {
    mobileSDKs: ['ios', 'android', 'flutter', 'react-native'],
    desktopSDKs: ['web', 'node', 'python', 'php', 'ruby', 'go', 'dotnet', 'elixir'],
    volumeThresholds: { low: 10, medium: 50, high: Infinity },
    ageThresholds: { warnAfterWeeks: 8, criticalAfterWeeks: 16 },
}

/**
 * Calculate the age of a version in days based on its release date
 *
 * @param releaseDate - ISO date string when the version was released
 * @returns Number of days since the release
 */
export function calculateVersionAge(releaseDate: string): number {
    const release = new Date(releaseDate)
    const now = new Date()
    return Math.floor((now.getTime() - release.getTime()) / (1000 * 60 * 60 * 24))
}

/**
 * Determine the device context (mobile/desktop/mixed) for an SDK type
 *
 * @param sdkType - The SDK type to categorize
 * @returns 'mobile', 'desktop', or 'mixed' based on SDK type
 */
export function determineDeviceContext(sdkType: SdkType): 'mobile' | 'desktop' | 'mixed' {
    if (DEVICE_CONTEXT_CONFIG.mobileSDKs.includes(sdkType)) {
        return 'mobile'
    }
    if (DEVICE_CONTEXT_CONFIG.desktopSDKs.includes(sdkType)) {
        return 'desktop'
    }
    return 'mixed'
}

/**
 * Categorize event volume based on event count
 *
 * @param count - Number of events detected
 * @returns 'low' (<10), 'medium' (10-50), or 'high' (>50)
 */
export function categorizeEventVolume(count: number): 'low' | 'medium' | 'high' {
    if (count < DEVICE_CONTEXT_CONFIG.volumeThresholds.low) {
        return 'low'
    }
    if (count < DEVICE_CONTEXT_CONFIG.volumeThresholds.medium) {
        return 'medium'
    }
    return 'high'
}
