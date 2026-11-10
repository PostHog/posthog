import { JsonObject, parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { hostKey, HostSchema, type Host } from '@/posthog/host'

import { StoredSecretSchema } from './helpers'
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

    async hosts(): Promise<Host[]> {
        return Object.keys(await this.readAll()).flatMap((key) => HostSchema.safeParse(key).data ?? [])
    }

    async read(host: Host): Promise<StoredSecret | undefined> {
        // A stored value hog doesn't recognize, such as one a later version wrote, reads as no login.
        return StoredSecretSchema.safeParse((await this.readAll())[hostKey(host)]).data
    }

    async write(host: Host, secret: StoredSecret): Promise<void> {
        const all = await this.readAll()
        all[hostKey(host)] = secret
        await this.runtime.writePrivateFile(this.path, JSON.stringify(all, null, 2))
    }

    async remove(host: Host): Promise<boolean> {
        const key = hostKey(host)
        return this.removeKeys((name) => name === key)
    }

    // Removes the entries under a name that isn't a host, such as one an older hog wrote, which
    // `hosts` leaves out.
    async removeUnreadable(): Promise<boolean> {
        return this.removeKeys((name) => HostSchema.safeParse(name).data === undefined)
    }

    private async removeKeys(matches: (name: string) => boolean): Promise<boolean> {
        const all = await this.readAll()
        const kept = Object.fromEntries(Object.entries(all).filter(([name]) => !matches(name)))
        if (Object.keys(kept).length === Object.keys(all).length) {
            return false
        }
        if (Object.keys(kept).length === 0) {
            await this.runtime.removeFile(this.path)
        } else {
            await this.runtime.writePrivateFile(this.path, JSON.stringify(kept, null, 2))
        }
        return true
    }
}
