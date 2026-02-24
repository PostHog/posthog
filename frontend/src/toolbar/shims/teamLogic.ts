import { kea, path, reducers, selectors } from 'kea'

// Toolbar shim — prevents the real teamLogic from auto-mounting and making API requests to the wrong host
export function isAuthenticatedTeam(team: unknown): boolean {
    return !!team && typeof team === 'object' && 'api_token' in team
}

export const teamLogic = kea([
    path(['toolbar', 'shims', 'teamLogic']),
    reducers({
        currentTeam: [null as Record<string, unknown> | null, {}],
    }),
    selectors({
        timezone: [(s) => [s.currentTeam], (): string => 'UTC'],
        weekStartDay: [(s) => [s.currentTeam], (): number => 0],
    }),
])
