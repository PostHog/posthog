import { Hub, RawPerson } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { CyclotronPerson } from '../../types'

export class PersonManagerService {
    constructor(private hub: Hub) {}

    public async getPerson(uuid: CyclotronPerson['id']): Promise<CyclotronPerson | null> {
        return (await this.getPersons([uuid]))[uuid]
    }

    public async getPersons(
        ids: CyclotronPerson['id'][]
    ): Promise<Record<CyclotronPerson['id'], CyclotronPerson | null>> {
        const personsById = await this.fetchPersons(ids)

        return ids.reduce<Record<string, CyclotronPerson | null>>((acc, id) => {
            acc[id] = personsById[id] ?? null
            return acc
        }, {})
    }

    // NOTE: Currently this essentially loads the "latest" template each time. We may need to swap this to using a specific version
    private async fetchPersons(teamDistinctIds: [number, string][]): Promise<Record<string, CyclotronPerson | null>> {
        logger.info('[PersonManager]', 'Fetching persons', { teamDistinctIds })

        // TODO: Add team ID check - also do we want to swap to using the distinct_id instead via a join. Feels much safer and would account for merges...
        const response = await this.hub.postgres.query<RawPerson>(
            PostgresUse.PERSONS_READ,
            `SELECT
                posthog_person.id,
                posthog_person.uuid,
                posthog_person.created_at,
                posthog_person.team_id,
                posthog_person.properties,
                posthog_person.properties_last_updated_at,
                posthog_person.properties_last_operation,
                posthog_person.is_user_id,
                posthog_person.version,
                posthog_person.is_identified
            FROM posthog_person
            JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id)
            WHERE
                posthog_person.team_id = $1
                AND posthog_persondistinctid.team_id = $1
                AND posthog_persondistinctid.distinct_id = $2`,
            teamDistinctIds,
            'fetchCyclotronPersons'
        )

        const persons = response.rows

        return persons.reduce<Record<string, CyclotronPerson | null>>((acc, person) => {
            acc[person.uuid] = person
            return acc
        }, {})
    }
}
