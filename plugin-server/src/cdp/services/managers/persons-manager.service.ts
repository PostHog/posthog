import { Hub, RawPerson } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { DBHogFunctionTemplate } from '../../types'

export type PersonGetArgs = {
    teamId: number
    distinctId: string
}

const toKey = (args: PersonGetArgs) => `${args.teamId}:${args.distinctId}`

const fromKey = (key: string): PersonGetArgs => {
    const [teamId, distinctId] = key.split(':')
    return { teamId: parseInt(teamId), distinctId }
}

export class PersonManagerService {
    private lazyLoader: LazyLoader<DBHogFunctionTemplate>

    constructor(private hub: Hub) {
        this.lazyLoader = new LazyLoader({
            name: 'person_manager',
            loader: async (ids) => await this.fetchPersons(ids),
        })
    }

    public async get(args: PersonGetArgs): Promise<DBHogFunctionTemplate | null> {
        const key = toKey(args)
        return (await this.lazyLoader.get(key)) ?? null
    }

    public async getMany(args: PersonGetArgs[]): Promise<Record<string, DBHogFunctionTemplate | null>> {
        const keys = args.map(toKey)
        return await this.lazyLoader.getMany(keys)
    }

    // NOTE: Currently this essentially loads the "latest" template each time. We may need to swap this to using a specific version
    private async fetchPersons(ids: string[]): Promise<Record<string, DBHogFunctionTemplate | undefined>> {
        const teamPersons = ids.map(fromKey)

        logger.info('[PersonManager]', 'Fetching persons', { teamPersons })

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
                posthog_person.is_identified
            FROM posthog_person
            JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id)
            WHERE
                posthog_person.team_id = $1
                AND posthog_persondistinctid.team_id = $1
                AND posthog_persondistinctid.distinct_id = $2`

        const response = await this.hub.postgres.query<RawPerson>(
            PostgresUse.PERSONS_READ,
            queryString,
            [ids],
            'fetchCDPPersons'
        )

        const personRows = response.rows

        return {}
    }
}
