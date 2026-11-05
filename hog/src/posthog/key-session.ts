import type { Runtime } from '@/core/runtime'

import type { AccessKey, AccessKeyStorage } from './access-key'
import type { BearerToken } from './tokens'

// A command can outlive an OAuth access token, so each request renews it first when it is about to
// expire, and renews it and sends once more when PostHog answers 401. PostHog checks the token
// before it does any work, so the second send is safe for a POST too.
export class KeySession {
    // PostHog also answers 401 for a valid token when the account can't act. Once a renewed token
    // gets 401 too, renewing again for every request would only rotate the login for nothing.
    private renewalHelps = true

    constructor(
        private readonly runtime: Runtime,
        private key: AccessKey,
        // Null for a key from the environment or --dotenv-file, which hog can't renew.
        private readonly storage: AccessKeyStorage | null
    ) {}

    get current(): AccessKey {
        return this.key
    }

    async token(): Promise<BearerToken> {
        if (this.storage) {
            this.key = await this.key.fresh(this.runtime, this.storage)
        }
        return this.key.token
    }

    async send<T>(attempt: (token: string) => Promise<T>, rejected: (result: T) => boolean): Promise<T> {
        const token = await this.token()
        const result = await attempt(token)
        if (!rejected(result) || !this.storage || !this.renewalHelps) {
            return result
        }
        const renewed = await this.key.fresh(this.runtime, this.storage, token)
        // A personal API key can't be renewed, so its 401 stands.
        if (renewed.token === token) {
            return result
        }
        this.key = renewed
        const retried = await attempt(renewed.token)
        this.renewalHelps = !rejected(retried)
        return retried
    }
}
