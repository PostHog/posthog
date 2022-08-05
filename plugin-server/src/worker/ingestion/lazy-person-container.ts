import { Hub, Person } from '../../types'

export class LazyPersonContainer {
    teamId: number
    distinctId: string

    loaded: boolean

    private hub: Hub
    private promise: Promise<Person | undefined> | null

    constructor(teamId: number, distinctId: string, hub: Hub, person: Person | undefined = undefined) {
        this.teamId = teamId
        this.distinctId = distinctId
        this.hub = hub

        if (person) {
            this.promise = Promise.resolve(person)
            this.loaded = true
        } else {
            this.promise = null
            this.loaded = false
        }
    }

    async get(): Promise<Person | undefined> {
        console.log('container.reset called', {
            teamId: this.teamId,
            distinctId: this.distinctId,
            loaded: this.loaded,
        })
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

    with(person: Person): LazyPersonContainer {
        console.log('container.with called', {
            teamId: this.teamId,
            distinctId: this.distinctId,
            loaded: this.loaded,
        })
        return new LazyPersonContainer(this.teamId, this.distinctId, this.hub, person)
    }

    reset(): LazyPersonContainer {
        console.log('container.reset called', {
            teamId: this.teamId,
            distinctId: this.distinctId,
            loaded: this.loaded,
        })
        return new LazyPersonContainer(this.teamId, this.distinctId, this.hub)
    }
}
