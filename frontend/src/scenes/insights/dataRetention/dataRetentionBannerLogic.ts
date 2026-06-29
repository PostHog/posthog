import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

import type { dataRetentionBannerLogicType } from './dataRetentionBannerLogicType'

const SNOOZE_DAYS = 30
// Don't nag accounts that can't yet have at-risk data: only warn once the account is within 90 days of its
// retention horizon (or past it).
const WARN_WITHIN_DAYS = 90

// Humanize a retention window in months: whole years read as "N year(s)", otherwise "N month(s)".
function retentionMonthsLabel(months: number): string {
    if (months % 12 === 0) {
        const years = months / 12
        return `${years} year${years === 1 ? '' : 's'}`
    }
    return `${months} month${months === 1 ? '' : 's'}`
}

// Global (per-browser) snooze + plan-derived eligibility for the events data-retention warning. The per-insight
// "does this query's range exceed retention" check lives in insightRetentionBannerLogic; this one stays a singleton
// so the snooze is shared across every insight rather than dismissed once per insight.
export const dataRetentionBannerLogic = kea<dataRetentionBannerLogicType>([
    path(['scenes', 'insights', 'dataRetention', 'dataRetentionBannerLogic']),
    connect({
        values: [teamLogic, ['currentTeam'], organizationLogic, ['currentOrganization']],
    }),
    actions({
        snooze: true,
    }),
    reducers({
        snoozedUntil: [
            null as string | null,
            { persist: true },
            {
                snooze: () => dayjs().add(SNOOZE_DAYS, 'day').toISOString(),
            },
        ],
    }),
    selectors({
        retentionEnforced: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!(currentTeam as TeamType | null)?.events_retention_enforced,
        ],
        retentionMonths: [
            (s) => [s.currentTeam],
            (currentTeam): number | null => (currentTeam as TeamType | null)?.event_retention_months ?? null,
        ],
        retentionPeriodLabel: [
            (s) => [s.retentionMonths],
            (retentionMonths): string | null => (retentionMonths ? retentionMonthsLabel(retentionMonths) : null),
        ],
        isSnoozed: [
            (s) => [s.snoozedUntil],
            (snoozedUntil): boolean => !!snoozedUntil && dayjs(snoozedUntil).isAfter(dayjs()),
        ],
        accountAgeEligible: [
            (s) => [s.currentOrganization, s.retentionMonths],
            (currentOrganization, retentionMonths): boolean => {
                if (!currentOrganization?.created_at || !retentionMonths) {
                    return false
                }
                // Eligible once the account is old enough to have data within 90 days of (or past) its retention
                // horizon — i.e. created before now − retention + 90 days.
                const horizon = dayjs().subtract(retentionMonths, 'month').add(WARN_WITHIN_DAYS, 'day')
                return dayjs(currentOrganization.created_at).isBefore(horizon)
            },
        ],
        warningEligible: [
            (s) => [s.retentionEnforced, s.accountAgeEligible, s.isSnoozed],
            (retentionEnforced, accountAgeEligible, isSnoozed): boolean =>
                retentionEnforced && accountAgeEligible && !isSnoozed,
        ],
    }),
])
