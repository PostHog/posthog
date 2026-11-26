import { logger } from '~/common/utils/logger'

// ai_events partitions by the month a row expires in, so events that arrive together spread over one partition
// per distinct retention. A few tiers keep the partitions each insert touches few, however many teams are listed.
const RETENTION_DAYS_TIERS = [30, 60, 90, 180, 365]

export function parseAiEventsRetentionDaysByTeam(raw: string): ReadonlyMap<number, number> {
    const retentionDaysByTeam = new Map<number, number>()
    if (raw.trim() === '') {
        return retentionDaysByTeam
    }
    for (const entry of raw.split(',')) {
        const match = /^ *([0-9]+):([0-9]+) *$/.exec(entry)
        const teamId = Number(match?.[1])
        const days = Number(match?.[2])
        if (!match || !RETENTION_DAYS_TIERS.includes(days) || retentionDaysByTeam.has(teamId)) {
            // The Django settings parser skips the same entries, so both sides agree on what a malformed value means.
            logger.error('AI_EVENTS_RETENTION_DAYS_BY_TEAM has an invalid entry, skipping it', {
                entry,
                expected: `team_id:days, days one of ${RETENTION_DAYS_TIERS.join(', ')}, each team once`,
            })
            continue
        }
        retentionDaysByTeam.set(teamId, days)
    }
    return retentionDaysByTeam
}
