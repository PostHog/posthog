import LRUCache from 'lru-cache'

import { CyclotronPerson } from '~/cdp/types'

import { Hub } from '../../../types'

const PERSONS_CACHE_AGE_MS = 60 * 1000 // 1 minute
const PERSONS_CACHE_MAX_SIZE = 100_000 // 100k entries

export class PersonsManagerService {
    private personsCache: LRUCache<string, CyclotronPerson>

    constructor(private hub: Hub) {
        this.personsCache = new LRUCache({ max: PERSONS_CACHE_MAX_SIZE, maxAge: PERSONS_CACHE_AGE_MS })
    }

    public async getPerson(teamId: number, distinctId: string): Promise<CyclotronPerson> {
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
            properties: rawPerson.properties ? { ...rawPerson.properties } : {},
        }
        this.personsCache.set(distinctId, person)
        return person
    }
}
