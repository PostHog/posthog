import { ValueMatcher } from '~/types'

/**
 * The rollout gate those features share: an allowlist ('*' or explicit team
 * IDs) minus an exclusion list, where exclusion always wins.
 */
export function buildTeamGate(teams: number[] | '*', excludedTeams: number[]): ValueMatcher<number> {
    const allowed = teams === '*' ? '*' : new Set(teams)
    const excluded = new Set(excludedTeams)
    return (teamId) => !excluded.has(teamId) && (allowed === '*' || allowed.has(teamId))
}
