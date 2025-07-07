import LRUCache from 'lru-cache'

import { Hub } from '../../../types'

type PersonProperties = Record<string, any>
type Person = {
    id: string
    properties: PersonProperties
}

const PERSONS_CACHE_AGE_MS = 60 * 1000 // 1 minute

export class PersonsManagerService {
    private personsCache: LRUCache<string, Person>

    constructor(private hub: Hub) {
        this.personsCache = new LRUCache({ max: 1_000_000, maxAge: PERSONS_CACHE_AGE_MS })
    }

    public async getPerson(teamId: number, distinctId: string): Promise<Person> {
        const cachedProperties = this.personsCache.get(distinctId)
        if (cachedProperties) {
            return cachedProperties
        }

        const rawPerson = await this.hub.db.fetchPerson(teamId, distinctId)

        if (!rawPerson) {
            throw new Error(`Person not found for team ${teamId} and distinctId ${distinctId}`)
        }

        const person = {
            id: rawPerson.id,
            properties: rawPerson.properties || {},
        }
        this.personsCache.set(distinctId, person)
        return person
    }
}
