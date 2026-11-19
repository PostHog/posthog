const MIN_RETENTION_DAYS = 30
const MAX_RETENTION_DAYS = 365

export function parseAiEventsRetentionDaysByTeam(raw: string): ReadonlyMap<number, number> {
    const retentionDaysByTeam = new Map<number, number>()
    if (raw.trim() === '') {
        return retentionDaysByTeam
    }
    for (const entry of raw.split(',')) {
        const match = /^ *([0-9]+):([0-9]+) *$/.exec(entry)
        const teamId = Number(match?.[1])
        const days = Number(match?.[2])
        if (!match || days < MIN_RETENTION_DAYS || days > MAX_RETENTION_DAYS || retentionDaysByTeam.has(teamId)) {
            throw new Error(
                `AI_EVENTS_RETENTION_DAYS_BY_TEAM has an invalid entry "${entry}": expected team_id:days, ` +
                    `days from ${MIN_RETENTION_DAYS} to ${MAX_RETENTION_DAYS}, each team once`
            )
        }
        retentionDaysByTeam.set(teamId, days)
    }
    return retentionDaysByTeam
}
