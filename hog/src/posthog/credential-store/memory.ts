import type { ItemName } from './item-name'
import type { CredentialStore, StoredSecret } from './types'

export class MemoryStore implements CredentialStore {
    readonly kind = 'memory'
    readonly path = null
    private readonly items = new Map<ItemName, StoredSecret>()

    async read(name: ItemName): Promise<StoredSecret | undefined> {
        return this.items.get(name)
    }

    async write(name: ItemName, secret: StoredSecret): Promise<void> {
        this.items.set(name, secret)
    }

    async remove(name: ItemName): Promise<boolean> {
        return this.items.delete(name)
    }
}
