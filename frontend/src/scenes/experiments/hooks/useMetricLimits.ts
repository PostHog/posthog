import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

// Team-specific metric limits mapping
// This should match the backend _TEAM_METRIC_LIMITS in ExperimentSerializer
const TEAM_METRIC_LIMITS: Record<number, number> = {
    // Add team/project IDs and their custom limits here
    // Example: 123: 20,  // Team 123 gets 20 metrics limit
}

// Default limit that matches the backend
const DEFAULT_METRIC_LIMIT = 10

/**
 * Get the experiment metric quantity limit for a specific team.
 * Returns the custom limit for the team if configured,
 * otherwise returns the default limit of 10.
 * 
 * This function mirrors the backend logic in ExperimentSerializer.get_experiment_metric_limit()
 */
export function getMetricLimits(teamId: number | null): { primary: number; secondary: number } {
    if (teamId === null) {
        return { primary: DEFAULT_METRIC_LIMIT, secondary: DEFAULT_METRIC_LIMIT }
    }
    
    const limit = TEAM_METRIC_LIMITS[teamId] ?? DEFAULT_METRIC_LIMIT
    return { primary: limit, secondary: limit }
}

/**
 * Hook to get the current team's experiment metric limits.
 * Returns both primary and secondary metric limits.
 */
export function useMetricLimits(): { primary: number; secondary: number } {
    const { currentTeamId } = useValues(teamLogic)
    return getMetricLimits(currentTeamId)
}