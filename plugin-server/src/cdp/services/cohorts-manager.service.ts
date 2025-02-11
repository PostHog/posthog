import { Hub } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { HogFunctionInvocationGlobals } from '../types'

export class CohortsManagerService {
    constructor(private hub: Hub) {}

    private async fetchPersonsCohorts(
        items: Record<string, { teamId: number; personId: string }>
    ): Promise<Record<string, { teamId: number; personId: string; cohorts: number[] }>> {
        const query = `SELECT pcp.cohort_id, pp.uuid, pp.team_id
                    FROM posthog_cohortpeople AS pcp
                    JOIN posthog_cohort pc ON pcp.cohort_id = pc.id
                    JOIN posthog_person pp ON pcp.person_id = pp.id
                    WHERE pcp.version IS NOT DISTINCT FROM pc.version
                    AND (pp.uuid, pp.team_id) IN (${Object.values(items)
                        .map((x) => `('${x.personId}', ${x.teamId})`)
                        .join(',')})`
        const results = (await this.hub.postgres.query(PostgresUse.COMMON_READ, query, [], 'fetchPersonsCohorts')).rows

        const responseItems: Record<string, { teamId: number; personId: string; cohorts: number[] }> = {}

        results.forEach((x) => {
            if (!responseItems[`${x.team_id}:${x.person_id}`]) {
                responseItems[`${x.team_id}:${x.person_id}`] = { teamId: x.team_id, personId: x.person_id, cohorts: [] }
            }

            responseItems[`${x.team_id}:${x.person_id}`].cohorts.push(x.cohort_id)
        })

        return responseItems
    }

    public async enrichCohorts(items: HogFunctionInvocationGlobals[]): Promise<HogFunctionInvocationGlobals[]> {
        const itemsNeedingCohorts = items.filter((x) => !x.cohorts)
        const teamAndPersonIds: Record<string, { teamId: number; personId: string }> = {}

        itemsNeedingCohorts.forEach((x) => {
            if (!x.person?.id || teamAndPersonIds[`${x.project.id}:${x.person.id}`]) {
                return
            }
            teamAndPersonIds[`${x.project.id}:${x.person.id}`] = { teamId: x.project.id, personId: x.person.id }
        })

        const results = await this.fetchPersonsCohorts(teamAndPersonIds)

        items.forEach((x) => {
            x.cohorts = []
            if (!x.person?.id || !results[`${x.project.id}:${x.person.id}`]) {
                return
            }
            x.cohorts = results[`${x.project.id}:${x.person.id}`].cohorts
        })

        return items
    }
}
