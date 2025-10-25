import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { PersonRepository } from '../../../worker/ingestion/persons/repositories/person-repository'

export type PersonGetArgs = {
    teamId: number
    distinctId: string
}

const toKey = (args: PersonGetArgs): string => `${args.teamId}:${args.distinctId}`

const fromKey = (key: string): PersonGetArgs => {
    const [teamId, distinctId] = key.split(':')
    return { teamId: parseInt(teamId), distinctId }
}

export type PersonManagerPerson = {
    id: string
    properties: Record<string, any>
    team_id: number
    distinct_id: string
}

export class PersonsManagerService {
    private lazyLoader: LazyLoader<PersonManagerPerson>

    constructor(private personRepository: PersonRepository) {
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

        logger.debug('[PersonManager]', 'Fetching persons', { teamPersons })

        const personRows = await this.personRepository.fetchPersonsByDistinctIds(teamPersons)

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
