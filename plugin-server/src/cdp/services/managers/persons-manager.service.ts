import { Hub, RawPerson } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'

export type PersonGetArgs = {
    teamId: number
    distinctId: string
}

const toKey = (args: PersonGetArgs): string => `${args.teamId}:${args.distinctId}`

const fromKey = (key: string): PersonGetArgs => {
    const [teamId, distinctId] = key.split(':')
    return { teamId: parseInt(teamId), distinctId }
}

// Type for the query result that includes distinct_id
type PersonWithDistinctId = RawPerson & {
    distinct_id: string
}

export type PersonManagerPerson = {
    id: string
    properties: Record<string, any>
    team_id: number
    distinct_id: string
}

export class PersonsManagerService {
    private lazyLoader: LazyLoader<PersonManagerPerson>

    constructor(private hub: Hub) {
        this.lazyLoader = new LazyLoader({
            name: 'person_manager',
            loader: async (ids) => await this.fetchPersons(ids),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
    }

    public async get(args: PersonGetArgs): Promise<PersonManagerPerson | null> {
        const key = toKey(args)
        return (await this.lazyLoader.get(key)) ?? null
    }

    public async getMany(args: PersonGetArgs[]): Promise<Record<string, PersonManagerPerson | null>> {
        const keys = args.map(toKey)
        return await this.lazyLoader.getMany(keys)
    }

    // NOTE: Currently this essentially loads the "latest" template each time. We may need to swap this to using a specific version
    private async fetchPersons(ids: string[]): Promise<Record<string, PersonManagerPerson | undefined>> {
        const teamPersons = ids.map(fromKey)

        logger.info('[PersonManager]', 'Fetching persons', { teamPersons })

        // Build the WHERE clause for multiple team_id, distinct_id pairs
        const conditions = teamPersons
            .map((_, index) => {
                const teamIdParam = index * 2 + 1
                const distinctIdParam = index * 2 + 2
                // NOTE: We have an index on posthog_persondistinctid (team_id, distinct_id) so filtering at that level should be more efficient
                return `(posthog_persondistinctid.team_id = $${teamIdParam} AND posthog_persondistinctid.distinct_id = $${distinctIdParam})`
            })
            .join(' OR ')

        const queryString = `SELECT
                posthog_person.id,
                posthog_person.uuid,
                posthog_person.created_at,
                posthog_person.team_id,
                posthog_person.properties,
                posthog_person.properties_last_updated_at,
                posthog_person.properties_last_operation,
                posthog_person.is_user_id,
                posthog_person.version,
                posthog_person.is_identified,
                posthog_persondistinctid.distinct_id
            FROM posthog_person
            JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id)
            WHERE ${conditions}`

        // Flatten the parameters: [teamId1, distinctId1, teamId2, distinctId2, ...]
        const params = teamPersons.flatMap((person) => [person.teamId, person.distinctId])

        const response = await this.hub.postgres.query<PersonWithDistinctId>(
            PostgresUse.PERSONS_READ,
            queryString,
            params,
            'fetchCDPPersons'
        )

        const personRows = response.rows

        // Map results back to the original keys
        const result: Record<string, PersonManagerPerson | undefined> = {}

        for (const row of personRows) {
            const key = toKey({ teamId: row.team_id, distinctId: row.distinct_id })

            result[key] = {
                id: row.uuid,
                properties: row.properties,
                team_id: row.team_id,
                distinct_id: row.distinct_id,
            }
        }

        return result
    }
}
