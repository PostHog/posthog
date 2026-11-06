import { PersonHogClient } from './client'
import { PersonHogConfig, createPersonHogClient } from './index'

/**
 * Scope owner for a PersonHog gRPC client: builds the client on `start()` and
 * closes the connection on `stop()`, so its lifetime is tied to the owning
 * scope. Throws if personhog isn't configured — read-only lanes (AI, error
 * tracking) read person and group data through it.
 */
export class PersonHogClientComponent {
    constructor(private readonly config: PersonHogConfig) {}

    start(): Promise<{ value: PersonHogClient; stop: () => Promise<void> }> {
        const client = createPersonHogClient(this.config)
        if (!client) {
            throw new Error(
                'PersonHog client is required but not configured — set PERSONHOG_ENABLED=true and PERSONHOG_ADDR'
            )
        }
        return Promise.resolve({
            value: client,
            stop: () => {
                client.close()
                return Promise.resolve()
            },
        })
    }
}
