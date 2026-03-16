import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { PersonRepository } from '../../../worker/ingestion/persons/repositories/person-repository'

export type PersonGetArgs = {
    teamId: number
    id: string
}

const toKey = (args: PersonGetArgs): string => `${args.teamId}:${args.id}`

const fromKey = (key: string): PersonGetArgs => {
    const [teamId, ...idParts] = key.split(':')
    return { teamId: parseInt(teamId), id: idParts.join(':') }
}

export type PersonManagerPerson = {
    id: string
    properties: Record<string, any>
    team_id: number
}

export type PersonManagerPersonWithDistinctId = PersonManagerPerson & {
    distinct_id: string
}

export class PersonsManagerService {
    private lazyLoader: LazyLoader<PersonManagerPerson>

    constructor(
        private personRepository: PersonRepository,
        lookupMode: 'distinct_id' | 'person_id' = 'distinct_id'
    ) {
        this.lazyLoader = new LazyLoader({
            name: `person_manager_lookup_by_${lookupMode}`,
            loader: async (ids) => {
                return lookupMode === 'distinct_id'
                    ? await this.fetchPersonsByDistinctIds(ids)
                    : await this.fetchPersonsByPersonIds(ids)
            },
            refreshAgeMs: 1000 * 60, // 1 minute, so that we don't hold stale person data for too long
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

    private async fetchPersonsByDistinctIds(
        ids: string[]
    ): Promise<Record<string, PersonManagerPersonWithDistinctId | undefined>> {
        const teamPersons = ids.map(fromKey)

        logger.debug('[PersonManager]', 'Fetching persons', { teamPersons })

        const personRows = await this.personRepository.fetchPersonsByDistinctIds(
            teamPersons.map(({ teamId, id }) => ({ teamId, distinctId: id }))
        )

        // Map results back to the original keys
        const result: Record<string, PersonManagerPersonWithDistinctId | undefined> = {}

        for (const row of personRows) {
            const key = toKey({ teamId: row.team_id, id: row.distinct_id })

            result[key] = {
                id: row.uuid,
                properties: row.properties,
                team_id: row.team_id,
                distinct_id: row.distinct_id,
            }
        }

        return result
    }

    private async fetchPersonsByPersonIds(ids: string[]): Promise<Record<string, PersonManagerPerson | undefined>> {
        const teamPersons = ids.map(fromKey)

        logger.debug('[PersonManager]', 'Fetching persons', { teamPersons })

        const personRows = await this.personRepository.fetchPersonsByPersonIds(
            teamPersons.map(({ teamId, id }) => ({ teamId, personId: id }))
        )

        // Map results back to the original keys
        const result: Record<string, PersonManagerPerson | undefined> = {}

        for (const row of personRows) {
            const key = toKey({ teamId: row.team_id, id: row.uuid })

            result[key] = {
                id: row.uuid,
                properties: row.properties,
                team_id: row.team_id,
            }
        }

        return result
    }
}
