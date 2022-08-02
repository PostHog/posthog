import { Hub, Person } from '../../types'

export class LazyPersonContainer {
    teamId: number
    distinctId: string

    loaded: boolean

    private hub: Hub
    private promise: Promise<Person | undefined> | null

    constructor(teamId: number, distinctId: string, hub: Hub) {
        this.teamId = teamId
        this.distinctId = distinctId
        this.hub = hub
        this.promise = null
        this.loaded = false
    }

    async get(): Promise<Person | undefined> {
        if (!this.promise) {
            this.promise = this.hub.db.fetchPerson(this.teamId, this.distinctId).then((person) => {
                if (person) {
                    this.loaded = true
                }
                return person
            })
        }
        return this.promise
    }

    set(person: Person): void {
        this.promise = Promise.resolve(person)
        this.loaded = true
    }
}
