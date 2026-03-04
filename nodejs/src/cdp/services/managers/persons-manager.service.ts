import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { TeamManager } from '../../../utils/team-manager'
import { PersonRepository } from '../../../worker/ingestion/persons/repositories/person-repository'
import { CyclotronPerson } from '../../types'
import { getPersonDisplayName } from '../../utils'

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
    private lazyLoaderByPersonId: LazyLoader<PersonManagerPerson>
    private lazyLoaderByDistinctId: LazyLoader<PersonManagerPersonWithDistinctId>

    constructor(
        private teamManager: TeamManager,
        private personRepository: PersonRepository,
        private siteUrl: string
    ) {
        this.lazyLoaderByPersonId = new LazyLoader({
            name: 'person_manager_lookup_by_person_id',
            loader: async (ids) => await this.fetchPersonsByPersonIds(ids),
            refreshAgeMs: 1000 * 60, // 1 minute, so that we don't hold stale person data for too long
        })
        this.lazyLoaderByDistinctId = new LazyLoader({
            name: 'person_manager_lookup_by_distinct_id',
            loader: async (ids) => await this.fetchPersonsByDistinctIds(ids),
            refreshAgeMs: 1000 * 60, // 1 minute, so that we don't hold stale person data for too long
        })
    }

    public clear(): void {
        this.lazyLoaderByPersonId.clear()
        this.lazyLoaderByDistinctId.clear()
    }

    public async getCyclotronPerson(
        teamId: number,
        id: string,
        kind: 'distinct_id' | 'person_id'
    ): Promise<CyclotronPerson | null> {
        const key = toKey({ teamId, id })

        const [team, dbPerson] = await Promise.all([
            this.teamManager.getTeam(teamId),
            kind === 'distinct_id' ? this.lazyLoaderByDistinctId.get(key) : this.lazyLoaderByPersonId.get(key),
        ])

        if (!dbPerson || !team) {
            return null
        }

        return {
            id: dbPerson.id,
            properties: dbPerson.properties,
            name: getPersonDisplayName(team, id, dbPerson.properties),
            url: `${this.siteUrl}/project/${teamId}/person/${encodeURIComponent(id)}`,
        }
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
