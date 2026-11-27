import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { Team } from '~/types'

export type DeactivatedOrganizationsMode = 'off' | 'shadow' | 'enforce'

export type AdmissionStage =
    | 'hog_function_trigger'
    | 'hog_flow_trigger'
    | 'hog_function_dispatch'
    | 'hog_flow_dispatch'
    | 'batch_export_invocation'

export const ORGANIZATION_DEACTIVATED_FAILURE = {
    errorKind: 'organization_deactivated',
    error: 'The organization is deactivated, so this invocation was skipped.',
}

const deactivatedOrganizationWork = new Counter({
    name: 'cdp_deactivated_organization_work_total',
    help: 'Events and invocations of an organization whose is_active is false. In shadow mode they run as before, and in enforce mode they are skipped.',
    labelNames: ['stage', 'mode'],
})

export function parseDeactivatedOrganizationsMode(value: string): DeactivatedOrganizationsMode {
    const mode = value.trim().toLowerCase()
    if (mode !== 'off' && mode !== 'shadow' && mode !== 'enforce') {
        throw new Error(`CDP_DEACTIVATED_ORGANIZATIONS_MODE must be off, shadow or enforce, got "${value}"`)
    }
    return mode
}

export class OrganizationAdmission {
    constructor(
        public readonly mode: DeactivatedOrganizationsMode,
        private teamManager: Pick<TeamManager, 'getTeams'>
    ) {}

    public skips(team: Pick<Team, 'organization_active'> | null): boolean {
        return this.mode === 'enforce' && team?.organization_active === false
    }

    public admits(team: Pick<Team, 'organization_active'> | null, stage: AdmissionStage): boolean {
        if (this.mode === 'off' || team?.organization_active !== false) {
            return true
        }
        deactivatedOrganizationWork.labels({ stage, mode: this.mode }).inc()
        return this.mode === 'shadow'
    }

    public async admitted<T>(items: T[], teamIdOf: (item: T) => number, stage: AdmissionStage): Promise<T[]> {
        if (!items.length) {
            return items
        }
        const teams = await this.teamsOf(items.map(teamIdOf))
        if (!teams) {
            return items
        }
        return items.filter((item) => this.admits(teams[String(teamIdOf(item))] ?? null, stage))
    }

    public async teamsOf(teamIds: number[]): Promise<Record<string, Team | null> | null> {
        if (this.mode === 'off' || !teamIds.length) {
            return null
        }
        try {
            return await this.teamManager.getTeams([...new Set(teamIds)])
        } catch (error) {
            if (this.mode === 'enforce') {
                throw error
            }
            logger.warn('⚠️', 'Could not load the teams to check their organizations, so their work runs', {
                error: String(error),
            })
            return null
        }
    }
}
