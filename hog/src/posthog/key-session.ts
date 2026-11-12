import { HogError } from '@/core/errors'
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
    // One renewal at a time, so concurrent requests share it instead of each renewing.
    private renewal: Promise<AccessKey> | undefined

    constructor(
        private readonly runtime: Runtime,
        private key: AccessKey,
        // Null for a key from the environment or --dotenv-file, which hog can't renew.
        private readonly storage: AccessKeyStorage | null
    ) {}

    get current(): AccessKey {
        return this.key
    }

    private async renew(storage: AccessKeyStorage, rejectedToken?: string): Promise<AccessKey> {
        while (this.renewal) {
            // A failed renewal fails its waiters too, so an outage costs one exchange and not one per request.
            await this.renewal
        }
        if (rejectedToken !== undefined && this.key.token !== rejectedToken) {
            return this.key
        }
        this.renewal = this.key
            .fresh(this.runtime, storage, rejectedToken)
            .then((key) => (this.key = key))
            .finally(() => {
                this.renewal = undefined
            })
        return this.renewal
    }

    async token(): Promise<BearerToken> {
        if (this.storage) {
            await this.renew(this.storage)
        }
        return this.key.token
    }

    // A step-up keeps the login id. Another id means a new login replaced this one while the command
    // ran, so hog stops instead of switching to it.
    async reload(): Promise<void> {
        const latest = await this.storage?.reread()
        if (!latest) {
            throw new HogError('not_authenticated', 'You logged out of hog.', 'Run `hog auth login` to log in again.')
        }
        if (latest.loginKey !== this.key.loginKey) {
            throw new HogError(
                'login_changed',
                'You logged in again while this command ran, so hog stopped instead of sending the rest of the command with the new login.',
                'Run the command again to use the new login.'
            )
        }
        this.key = latest
    }

    async send<T>(attempt: (token: string) => Promise<T>, rejected: (result: T) => boolean): Promise<T> {
        const token = await this.token()
        const result = await attempt(token)
        if (!rejected(result) || !this.storage || !this.renewalHelps) {
            return result
        }
        const renewed = await this.renew(this.storage, token)
        // A personal API key can't be renewed, so its 401 stands.
        if (renewed.token === token) {
            return result
        }
        const retried = await attempt(renewed.token)
        this.renewalHelps = !rejected(retried)
        return retried
    }
}
