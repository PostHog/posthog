/** Parses a comma-separated team ID allowlist from config; '*' means all teams. */
export function parseTeamsList(teamsStr: string): number[] | '*' {
    // Trim so a whitespace-padded '*' (easy to produce in Helm/YAML) is still
    // recognized as the wildcard rather than silently parsing as an empty list.
    if (teamsStr.trim() === '*') {
        return '*'
    }
    return teamsStr
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n))
}
