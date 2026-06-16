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

const RETENTION_PERIOD_TO_DAYS: Record<string, number> = {
    '1y': 365,
    '2y': 365 * 2,
    '3y': 365 * 3,
    '5y': 365 * 5,
    '7y': 365 * 7,
}

const RETENTION_PERIOD_TO_LABEL: Record<string, string> = {
    '1y': '1 year',
    '2y': '2 years',
    '3y': '3 years',
    '5y': '5 years',
    '7y': '7 years',
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
        retentionPeriodDays: [
            (s) => [s.currentTeam],
            (currentTeam): number | null => {
                const period = (currentTeam as TeamType | null)?.event_retention_period
                return period ? (RETENTION_PERIOD_TO_DAYS[period] ?? null) : null
            },
        ],
        retentionPeriodLabel: [
            (s) => [s.currentTeam],
            (currentTeam): string | null => {
                const period = (currentTeam as TeamType | null)?.event_retention_period
                return period ? (RETENTION_PERIOD_TO_LABEL[period] ?? null) : null
            },
        ],
        isSnoozed: [
            (s) => [s.snoozedUntil],
            (snoozedUntil): boolean => !!snoozedUntil && dayjs(snoozedUntil).isAfter(dayjs()),
        ],
        accountAgeEligible: [
            (s) => [s.currentOrganization, s.retentionPeriodDays],
            (currentOrganization, retentionPeriodDays): boolean => {
                if (!currentOrganization?.created_at || !retentionPeriodDays) {
                    return false
                }
                const accountAgeDays = dayjs().diff(dayjs(currentOrganization.created_at), 'day')
                return accountAgeDays >= retentionPeriodDays - WARN_WITHIN_DAYS
            },
        ],
        warningEligible: [
            (s) => [s.retentionEnforced, s.accountAgeEligible, s.isSnoozed],
            (retentionEnforced, accountAgeEligible, isSnoozed): boolean =>
                retentionEnforced && accountAgeEligible && !isSnoozed,
        ],
    }),
])
