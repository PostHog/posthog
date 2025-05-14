import { actions, kea, path, reducers, selectors, listeners, afterMount, connect } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { sidePanelSdkDoctorLogicType } from './sidePanelSdkDoctorLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { EventType, EventsListQueryParams } from '~/types'

export type SdkType = 'web' | 'ios' | 'android' | 'node' | 'python' | 'php' | 'ruby' | 'go' | 'flutter' | 'react-native' | 'other'
export type SdkVersionInfo = {
    type: SdkType
    version: string
    isOutdated: boolean
    count: number
}
export type SdkHealthStatus = 'healthy' | 'warning' | 'critical'

export const sidePanelSdkDoctorLogic = kea<sidePanelSdkDoctorLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelSdkDoctorLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        loadRecentEvents: true,
    }),

    loaders(({ values }) => ({
        recentEvents: [
            [] as EventType[],
            {
                loadRecentEvents: async () => {
                    // Force a fresh reload of events
                    const params: EventsListQueryParams = {
                        limit: 50,
                        orderBy: ['-timestamp'],
                        after: '-24h',
                    }
                    // Use a default team ID if currentTeamId is null
                    const teamId = values.currentTeamId || undefined
                    try {
                        const response = await api.events.list(params, 50, teamId)
                        return response.results
                    } catch (error) {
                        console.error('Error loading events:', error)
                        return [] // Return empty array on error
                    }
                },
            },
        ],
    })),

    reducers({
        sdkVersionsMap: [
            {} as Record<string, SdkVersionInfo>,
            {
                loadRecentEvents: () => ({}), // Clear the map when loading starts to ensure fresh data
                loadRecentEventsSuccess: (_, { recentEvents }) => {
                    const sdkVersionsMap: Record<string, SdkVersionInfo> = {}
                    
                    for (const event of recentEvents) {
                        const lib = event.properties?.$lib
                        const libVersion = event.properties?.$lib_version
                        
                        if (!lib || !libVersion) {
                            continue
                        }
                        
                        const key = `${lib}-${libVersion}`
                        
                        if (!sdkVersionsMap[key]) {
                            // Determine SDK type from lib name
                            let type: SdkType = 'other'
                            if (lib === 'web') type = 'web'
                            else if (lib === 'posthog-ios') type = 'ios'
                            else if (lib === 'posthog-android') type = 'android'
                            else if (lib === 'posthog-node') type = 'node'
                            else if (lib === 'posthog-python') type = 'python'
                            else if (lib === 'posthog-php') type = 'php'
                            else if (lib === 'posthog-ruby') type = 'ruby'
                            else if (lib === 'posthog-go') type = 'go'
                            else if (lib === 'posthog-flutter') type = 'flutter'
                            else if (lib === 'posthog-react-native') type = 'react-native'
                            
                            // Check if version is outdated
                            // For now, we'll use a simplified check - in reality, this would compare against
                            // known minimum versions for each SDK type
                            const isOutdated = checkIfVersionOutdated(lib, libVersion)
                            
                            sdkVersionsMap[key] = {
                                type,
                                version: libVersion,
                                isOutdated,
                                count: 1,
                            }
                        } else {
                            sdkVersionsMap[key].count += 1
                        }
                    }
                    
                    return sdkVersionsMap
                },
            },
        ],
    }),

    selectors({
        sdkVersions: [
            (s) => [s.sdkVersionsMap],
            (sdkVersionsMap: Record<string, SdkVersionInfo>): SdkVersionInfo[] => {
                return Object.values(sdkVersionsMap).sort((a, b) => b.count - a.count)
            },
        ],
        
        outdatedSdkCount: [
            (s) => [s.sdkVersions],
            (sdkVersions: SdkVersionInfo[]): number => {
                return sdkVersions.filter(sdk => sdk.isOutdated).length
            },
        ],
        
        sdkHealth: [
            (s) => [s.outdatedSdkCount],
            (outdatedSdkCount: number): SdkHealthStatus => {
                // If there are any outdated SDKs, mark as warning
                // If there are 3 or more, mark as critical
                if (outdatedSdkCount >= 3) {
                    return 'critical'
                } else if (outdatedSdkCount > 0) {
                    return 'warning'
                }
                return 'healthy'
            },
        ],
        
        needsAttention: [
            (s) => [s.sdkHealth],
            (sdkHealth: SdkHealthStatus): boolean => {
                // For the button to be visible, we need a non-healthy status
                return sdkHealth !== 'healthy'
            },
        ],
    }),
    
    listeners(({ actions }) => ({
        // When the logic is mounted or when loadRecentEvents is called,
        // load the recent events
    })),
    
    afterMount(({ actions }) => {
        // Load recent events when the logic is mounted
        actions.loadRecentEvents()
    }),
])

// Helper function to check if a version is outdated
function checkIfVersionOutdated(lib: string, version: string): boolean {
    // Parse the version string into components
    const components = version.split('.')
    if (components.length < 2) {
        return false // Can't determine
    }
    
    const major = parseInt(components[0])
    const minor = parseInt(components[1])
    
    // Mock implementation for now - to be replaced with actual minimum version requirements
    // Similar to how Session Recording checks for versions < 1.75
    if (lib === 'web' && (major === 1 && minor < 85)) {
        return true
    } else if (lib === 'posthog-ios' && (major === 1 && minor < 4)) {
        return true
    } else if (lib === 'posthog-android' && (major === 1 && minor < 4)) {
        return true
    } else if (lib === 'posthog-node' && (major === 1 && minor < 5)) {
        return true
    }
    
    // For all other SDKs, consider them up to date for now
    return false
}
