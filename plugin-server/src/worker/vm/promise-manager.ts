import { Hub } from '../../types'
import { Action, Team } from '../../types'
import { DB } from '../../utils/db/db'

export class PromiseManager {
    pendingPromises: number
    serverInstance: Hub

    constructor(server: Hub) {
        this.pendingPromises = 0
        this.serverInstance = server
    }

    // runPromiseInBackground? runPromise?
    public voidPromise(promise: () => Promise<any>) {
        if (this.pendingPromises > this.serverInstance.MAX_PENDING_PROMISES_PER_WORKER) {
            setTimeout(() => this.voidPromise(promise), this.serverInstance.WORKER_POSTPONE_PROMISE_TIMEOUT)
            return
        }

        const instrumentedPromise = async () => {
            ++this.pendingPromises
            await promise()
            --this.pendingPromises
        }

        void instrumentedPromise()
    }
}
