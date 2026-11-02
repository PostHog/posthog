import { randomUUID } from 'node:crypto'

import { HogError } from '@/core/errors'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

// The part of a login the credential store keeps. settings.json keeps the rest, so a keychain item
// stays small however many scopes a login gains.
export interface PersonalApiKeySecret {
    apiKey: string
}

export type StoredSecret = PersonalApiKeySecret

export type StoreKind = 'keychain' | 'file' | 'memory'

// The stores a login can use. The memory store exists for tests only.
export type StoreChoice = Exclude<StoreKind, 'memory'>

// Where hog keeps the secrets of the logins `hog auth login` saves, one per host. Commands only see
// this interface, so each store behaves the same to them.
export interface CredentialStore {
    readonly kind: StoreKind
    // The file that holds the secrets. Null for a store that isn't a file.
    readonly path: string | null
    read(host: string): Promise<StoredSecret | undefined>
    write(host: string, secret: StoredSecret): Promise<void>
    // Resolves to false when the store held nothing for the host.
    remove(host: string): Promise<boolean>
}

// The keychain dialog on macOS never times out by itself, and a person may not notice it, so hog
// says what it waits for and gives up on its own.
const KEYCHAIN_PROGRESS_MS = 2000
const KEYCHAIN_TIMEOUT_MS = 60_000
// A name no host can have, so the probe never touches a real login.
const PROBE_PREFIX = 'hog-keychain-probe'

// `https://eu.posthog.com/` and `https://eu.posthog.com` are the same login.
export function hostKey(host: string): string {
    return URL.canParse(host) ? new URL(host).origin : host
}

export function trimHost(host: string): string {
    return host.replace(/\/+$/, '')
}

// Keeps the path a self-hosted PostHog can sit under, such as https://example.com/posthog.
export function hostUrl(host: string, path: string): URL {
    return new URL(path, `${trimHost(host)}/`)
}

// A stored value hog doesn't recognize, such as one a later version wrote, reads as no login.
function parseSecret(value: unknown): StoredSecret | undefined {
    const item = value as Record<string, unknown> | null
    return typeof item?.apiKey === 'string' ? { apiKey: item.apiKey } : undefined
}

export function parseJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}

export class MemoryStore implements CredentialStore {
    readonly kind = 'memory'
    readonly path = null
    private readonly items = new Map<string, StoredSecret>()

    async read(host: string): Promise<StoredSecret | undefined> {
        return this.items.get(hostKey(host))
    }

    async write(host: string, secret: StoredSecret): Promise<void> {
        this.items.set(hostKey(host), secret)
    }

    async remove(host: string): Promise<boolean> {
        return this.items.delete(hostKey(host))
    }
}

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

function keychainError(error: unknown): HogError {
    if (error instanceof HogError) {
        return error
    }
    // Bun reports both "Deny" and "Cancel" in the macOS dialog with this code.
    if ((error as { code?: unknown } | null)?.code === 'ERR_SECRETS_USER_CANCELED') {
        return new HogError(
            'keychain_access_denied',
            'hog was not allowed to use the keychain.',
            'Run the command again and allow hog to use the keychain. Choose "Always Allow" so it does not ask again.'
        )
    }
    return new HogError(
        'keychain_unavailable',
        `hog couldn't use the keychain: ${error instanceof Error ? error.message : String(error)}`,
        'Unlock the keychain and run the command again, or run `hog auth login` to store your credentials in a file.'
    )
}

// Runs one keychain call. After a moment it tells the person a dialog may be waiting for them, and
// after KEYCHAIN_TIMEOUT_MS it stops waiting.
async function keychainCall<T>(runtime: Runtime, operation: () => Promise<T>): Promise<T> {
    const settled = new AbortController()
    void runtime.sleep(KEYCHAIN_PROGRESS_MS, settled.signal).then(() => {
        if (!settled.signal.aborted) {
            runtime.writeStderr('Waiting for access to the keychain. If a dialog asks, allow hog to use it.\n')
        }
    })
    const timeout = runtime.sleep(KEYCHAIN_TIMEOUT_MS, settled.signal).then((): never => {
        if (settled.signal.aborted) {
            return undefined as never
        }
        throw new HogError(
            'keychain_access_timeout',
            `hog stopped after waiting ${KEYCHAIN_TIMEOUT_MS / 1000} seconds for access to the keychain.`,
            'Close the keychain dialog that is still open. Then run the command again and click "Always Allow".'
        )
    })
    try {
        return await Promise.race([operation(), timeout])
    } catch (error) {
        throw keychainError(error)
    } finally {
        settled.abort()
    }
}

export class KeychainStore implements CredentialStore {
    readonly kind = 'keychain'
    readonly path = null

    constructor(private readonly runtime: Runtime) {}

    async read(host: string): Promise<StoredSecret | undefined> {
        const value = await keychainCall(this.runtime, () => this.runtime.secrets.get(hostKey(host)))
        return value === null ? undefined : parseSecret(parseJson(value))
    }

    async write(host: string, secret: StoredSecret): Promise<void> {
        await keychainCall(this.runtime, () => this.runtime.secrets.set(hostKey(host), JSON.stringify(secret)))
    }

    async remove(host: string): Promise<boolean> {
        return keychainCall(this.runtime, () => this.runtime.secrets.delete(hostKey(host)))
    }
}

type KeychainProbe = { usable: true } | { usable: false; reason: string }

// Writes an item, reads it back and deletes it. Any failure, including a person who denies the
// dialog, means hog keeps credentials in a file instead.
export async function probeKeychain(runtime: Runtime): Promise<KeychainProbe> {
    const value = randomUUID()
    // Its own item for each probe, so two logins that probe at once don't change each other's item.
    const name = `${PROBE_PREFIX}-${value}`
    try {
        await keychainCall(runtime, async () => {
            await runtime.secrets.set(name, value)
            const readBack = await runtime.secrets.get(name)
            await runtime.secrets.delete(name)
            if (readBack !== value) {
                throw new Error('it returned a different value than hog stored')
            }
        })
        return { usable: true }
    } catch (error) {
        return { usable: false, reason: error instanceof Error ? error.message : String(error) }
    }
}

export function openStore(runtime: Runtime, kind: StoreChoice): KeychainStore | FileStore {
    return kind === 'keychain' ? new KeychainStore(runtime) : new FileStore(runtime)
}
