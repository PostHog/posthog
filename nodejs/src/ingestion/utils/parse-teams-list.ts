/** Parses a comma-separated team ID allowlist from config; '*' means all teams. */
export function parseTeamsList(teamsStr: string): number[] | '*' {
    if (teamsStr === '*') {
        return '*'
    }
    return teamsStr
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n))
}
