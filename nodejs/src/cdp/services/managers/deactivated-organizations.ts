import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

const counterDeactivatedOrganizationNotLoaded = new Counter({
    name: 'cdp_deactivated_organization_not_loaded',
    help: 'A hog function or hog flow the CDP did not load, because staff deactivated its organization',
    labelNames: ['kind'],
})

export function organizationInactiveCondition(table: string): string {
    return `EXISTS (
        SELECT 1 FROM posthog_team t JOIN posthog_organization o ON o.id = t.organization_id
        WHERE t.id = ${table}.team_id AND o.is_active IS FALSE
    )`
}

export function organizationInactiveColumn(table: string): string {
    return `${organizationInactiveCondition(table)} AS organization_inactive`
}

export function withoutDeactivatedOrganizations<T extends { id: string; team_id: number }>(
    kind: 'hog_function' | 'hog_flow',
    rows: T[],
    keepWhenInactive: (row: T) => boolean = () => false
): T[] {
    const kept: T[] = []
    const skipped: T[] = []
    for (const row of rows as (T & { organization_inactive?: boolean })[]) {
        const inactive = row.organization_inactive === true
        delete row.organization_inactive
        if (inactive && !keepWhenInactive(row)) {
            skipped.push(row)
        } else {
            kept.push(row)
        }
    }
    if (skipped.length) {
        counterDeactivatedOrganizationNotLoaded.labels({ kind }).inc(skipped.length)
        logger.info('⏭️', 'Not loading the hog functions or flows of deactivated organizations', {
            kind,
            teamIds: [...new Set(skipped.map((row) => row.team_id))],
            ids: skipped.map((row) => row.id),
        })
    }
    return kept
}
