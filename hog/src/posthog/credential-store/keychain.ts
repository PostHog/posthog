import { randomUUID } from 'node:crypto'

import { HogError } from '@/core/errors'
import { parseJsonOrUndefined } from '@/core/json'
import type { Runtime } from '@/core/runtime'
import { hostKey, type Host } from '@/posthog/host'

import { StoredSecretSchema } from './helpers'
import type { CredentialStore, StoredSecret } from './types'

// The keychain dialog on macOS never times out by itself, and a person may not notice it, so hog
// says what it waits for and gives up on its own.
const KEYCHAIN_PROGRESS_MS = 2000
const KEYCHAIN_TIMEOUT_MS = 60_000
// A name no host can have, so the probe never touches a real login.
const PROBE_PREFIX = 'hog-keychain-probe'

function keychainError(error: unknown): HogError {
    if (error instanceof HogError) {
        return error
    }
    // Bun reports both "Deny" and "Cancel" in the macOS dialog with this code.
    if ((error as { code?: unknown } | null)?.code === 'ERR_SECRETS_USER_CANCELED') {
        return new HogError(
            'keychain_access_denied',
            "PostHog wasn't allowed to use the keychain.",
            'Run the command again and allow PostHog to use the keychain. Choose "Always Allow" so it doesn\'t ask again.'
        )
    }
    return new HogError(
        'keychain_unavailable',
        `hog couldn't use the keychain: ${error instanceof Error ? error.message : String(error)}`,
        'Unlock the keychain and run the command again, or run `hog auth login` to store your credentials in a file.'
    )
}

// Runs one keychain call. After a moment it tells the person a dialog may be waiting for them, and
// after KEYCHAIN_TIMEOUT_MS it stops waiting. The dialog can still be answered after that, so `undo`
// reverts a call that lands late.
async function keychainCall<T>(
    runtime: Runtime,
    operation: () => Promise<T>,
    undo?: () => Promise<unknown>
): Promise<T> {
    const settled = new AbortController()
    void runtime.sleep(KEYCHAIN_PROGRESS_MS, settled.signal).then(() => {
        if (!settled.signal.aborted) {
            runtime.writeStderr('Waiting for access to the keychain. If a dialog asks, allow PostHog to use it.\n')
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
    const pending = operation()
    try {
        return await Promise.race([pending, timeout])
    } catch (error) {
        if (undo && error instanceof HogError && error.code === 'keychain_access_timeout') {
            void pending.then(undo).catch(() => {})
        }
        throw keychainError(error)
    } finally {
        settled.abort()
    }
}

export class KeychainStore implements CredentialStore {
    readonly kind = 'keychain'
    readonly path = null

    constructor(private readonly runtime: Runtime) {}

    async read(host: Host): Promise<StoredSecret | undefined> {
        const value = await keychainCall(this.runtime, () => this.runtime.secrets.get(hostKey(host)))
        return value === null ? undefined : parseJsonOrUndefined(value, StoredSecretSchema)
    }

    async write(host: Host, secret: StoredSecret, options: { removeIfLate?: boolean } = {}): Promise<void> {
        const name = hostKey(host)
        await keychainCall(
            this.runtime,
            () => this.runtime.secrets.set(name, JSON.stringify(secret)),
            options.removeIfLate ? () => this.runtime.secrets.delete(name) : undefined
        )
    }

    async remove(host: Host): Promise<boolean> {
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
