import type { Runtime } from '@/core/runtime'

import type { AccessKey } from './access-key'
import type { Credentials } from './credentials'

// A command can outlive an OAuth access token, so each request renews it first when it is about to
// expire, and renews it and sends once more when PostHog answers 401. PostHog checks the token
// before it does any work, so the second send is safe for a POST too.
export class KeySession {
    private key: AccessKey

    constructor(
        private readonly runtime: Runtime,
        private readonly credentials: Credentials
    ) {
        this.key = credentials.key
    }

    get current(): AccessKey {
        return this.key
    }

    async token(): Promise<string> {
        if (this.credentials.source === 'store') {
            this.key = await this.key.fresh(this.runtime, this.credentials.storage)
        }
        return this.key.token
    }

    async send<T>(attempt: (token: string) => Promise<T>, rejected: (result: T) => boolean): Promise<T> {
        const token = await this.token()
        const result = await attempt(token)
        if (!rejected(result) || this.credentials.source !== 'store') {
            return result
        }
        const renewed = await this.key.fresh(this.runtime, this.credentials.storage, token)
        // A personal API key can't be renewed, so its 401 stands.
        if (renewed.token === token) {
            return result
        }
        this.key = renewed
        return attempt(renewed.token)
    }
}
