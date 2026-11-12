import { JsonObject, parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import type { ProjectId } from '@/posthog/ids'

import { StoredSecretSchema } from './helpers'
import { parseItemName, type ItemName, type LoginTarget } from './item-name'
import type { CredentialStore, StoredSecret } from './types'

// One JSON file, readable only by its owner, for machines without a keychain hog can use.
export class FileStore implements CredentialStore {
    readonly kind = 'file'

    readonly path: string

    constructor(private readonly runtime: Runtime) {
        this.path = hogFile(runtime, 'credentials.json')
    }

    private async readAll(): Promise<Record<string, unknown>> {
        let text: string
        try {
            text = await this.runtime.readFile(this.path)
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
                return {}
            }
            throw error
        }
        return parseJsonOrUndefined(text, JsonObject) ?? {}
    }

    async owners(): Promise<LoginTarget<ProjectId | null>[]> {
        return Object.keys(await this.readAll()).flatMap((name) => parseItemName(name) ?? [])
    }

    async read(name: ItemName): Promise<StoredSecret | undefined> {
        // A stored value hog doesn't recognize, such as one a later version wrote, reads as no login.
        return StoredSecretSchema.safeParse((await this.readAll())[name]).data
    }

    async write(name: ItemName, secret: StoredSecret): Promise<void> {
        const all = await this.readAll()
        all[name] = secret
        await this.runtime.writePrivateFile(this.path, JSON.stringify(all, null, 2))
    }

    async remove(name: ItemName): Promise<boolean> {
        return (await this.removeWhere((key) => key === name)).length > 0
    }

    async removeWhere(matches: (name: string) => boolean): Promise<string[]> {
        const all = await this.readAll()
        const removed = Object.keys(all).filter(matches)
        if (removed.length === 0) {
            return []
        }

        const kept = Object.fromEntries(Object.entries(all).filter(([name]) => !matches(name)))
        if (Object.keys(kept).length === 0) {
            await this.runtime.removeFile(this.path)
        } else {
            await this.runtime.writePrivateFile(this.path, JSON.stringify(kept, null, 2))
        }

        return removed
    }
}
