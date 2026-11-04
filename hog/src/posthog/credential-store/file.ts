import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { hostKey } from '@/posthog/host'

import { parseJson, parseSecret } from './helpers'
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
        const parsed = parseJson(text)
        return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : {}
    }

    async hosts(): Promise<string[]> {
        return Object.keys(await this.readAll())
    }

    async read(host: string): Promise<StoredSecret | undefined> {
        return parseSecret((await this.readAll())[hostKey(host)])
    }

    async write(host: string, secret: StoredSecret): Promise<void> {
        const all = await this.readAll()
        all[hostKey(host)] = secret
        await this.runtime.writePrivateFile(this.path, JSON.stringify(all, null, 2))
    }

    async remove(host: string): Promise<boolean> {
        const all = await this.readAll()
        const key = hostKey(host)
        if (!(key in all)) {
            return false
        }
        delete all[key]
        if (Object.keys(all).length === 0) {
            await this.runtime.removeFile(this.path)
        } else {
            await this.runtime.writePrivateFile(this.path, JSON.stringify(all, null, 2))
        }
        return true
    }
}
