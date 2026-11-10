import { hostKey, type Host, type HostKey } from '@/posthog/host'

import type { CredentialStore, StoredSecret } from './types'

export class MemoryStore implements CredentialStore {
    readonly kind = 'memory'
    readonly path = null
    private readonly items = new Map<HostKey, StoredSecret>()

    async read(host: Host): Promise<StoredSecret | undefined> {
        return this.items.get(hostKey(host))
    }

    async write(host: Host, secret: StoredSecret): Promise<void> {
        this.items.set(hostKey(host), secret)
    }

    async remove(host: Host): Promise<boolean> {
        return this.items.delete(hostKey(host))
    }
}
