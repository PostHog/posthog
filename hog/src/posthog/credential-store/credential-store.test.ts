import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'
import type { Secrets } from '@/core/runtime'
import { fakeRuntime, type FakeRuntime } from '@/testing'

import { FileStore } from './file'
import { KeychainStore } from './keychain'
import { MemoryStore } from './memory'
import type { CredentialStore, StoredSecret } from './types'

const EU = 'https://eu.posthog.com'
const US = 'https://us.posthog.com'

function secret(apiKey: string): StoredSecret {
    return { apiKey }
}

const US_OAUTH: StoredSecret = { accessToken: 'pha_access', refreshToken: 'phr_refresh' }

// A keychain that answers after `delayMs` of fake time, or never, or fails the way Bun reports a
// denied dialog.
function dialogSecrets(behavior: number | 'never' | 'denied'): (runtime: FakeRuntime) => Secrets {
    return (runtime) => {
        const answer = async <T>(value: T): Promise<T> => {
            if (behavior === 'never') {
                return new Promise<T>(() => {})
            }
            if (behavior === 'denied') {
                throw Object.assign(new Error('User canceled the operation.'), { code: 'ERR_SECRETS_USER_CANCELED' })
            }
            await runtime.sleep(behavior)
            return value
        }
        return {
            get: () => answer(JSON.stringify(secret('phx_slow'))),
            set: () => answer(undefined),
            delete: () => answer(true),
        }
    }
}

describe('credential stores', () => {
    describe.each([
        ['memory', (): CredentialStore => new MemoryStore()],
        ['file', (): CredentialStore => new FileStore(fakeRuntime())],
        ['keychain', (): CredentialStore => new KeychainStore(fakeRuntime())],
    ])('%s', (_kind, makeStore) => {
        test('keeps one secret per host, overwrites it and removes it', async () => {
            const store = makeStore()

            expect(await store.read(EU)).toBeUndefined()
            expect(await store.remove(EU)).toBe(false)

            await store.write(EU, secret('phx_first'))
            await store.write(US, US_OAUTH)
            await store.write(`${EU}/`, secret('phx_second'))

            expect(await store.read(EU)).toEqual(secret('phx_second'))
            expect(await store.read(US)).toEqual(US_OAUTH)

            expect(await store.remove(EU)).toBe(true)

            expect(await store.read(EU)).toBeUndefined()
            expect(await store.read(US)).toEqual(US_OAUTH)
        })
    })

    test("the file store writes a file only its owner can read, in hog's folder", async () => {
        const runtime = fakeRuntime()
        const privateFiles: string[] = []
        const write = runtime.writePrivateFile
        runtime.writePrivateFile = async (path, contents) => {
            privateFiles.push(path)
            await write(path, contents)
        }

        await new FileStore(runtime).write(EU, secret('phx_file'))

        expect(privateFiles).toEqual(['/home/test/.config/hog/credentials.json'])
    })

    test.each([
        ['answers at once', 0, 'phx_slow', false, 0],
        ['answers while a dialog is open', 5000, 'phx_slow', true, 5000],
        ['never answers', 'never' as const, 'keychain_access_timeout', true, 60_000],
        ['is denied', 'denied' as const, 'keychain_access_denied', false, 0],
    ])('a keychain that %s', async (_name, behavior, expected, warns, elapsedMs) => {
        const runtime = fakeRuntime({ secrets: dialogSecrets(behavior) })
        const start = runtime.now()

        const outcome = await new KeychainStore(runtime).read(EU).then(
            (stored) => (stored && 'apiKey' in stored ? stored.apiKey : stored),
            (error: unknown) => (error instanceof HogError ? error.code : error)
        )

        expect(outcome).toBe(expected)
        expect(runtime.stderr().includes('Waiting for access to the keychain')).toBe(warns)
        expect(runtime.now() - start).toBe(elapsedMs)
    })

    test.each([
        ['removed again when the caller stops using the keychain', true, {}],
        ['kept when the caller keeps using the keychain', false, { [EU]: JSON.stringify(secret('phx_late')) }],
    ])('a keychain write that lands after hog gave up is %s', async (_name, removeIfLate, keychain) => {
        const runtime = fakeRuntime()
        const items = runtime.secrets
        runtime.secrets = {
            ...items,
            set: async (name, value) => {
                await runtime.sleep(90_000)
                await items.set(name, value)
            },
        }

        const write = await new KeychainStore(runtime)
            .write(EU, secret('phx_late'), { removeIfLate })
            .catch((error: unknown) => error)
        await runtime.sleep(60_000)

        expect((write as HogError).code).toBe('keychain_access_timeout')
        expect(runtime.keychain).toEqual(keychain)
    })
})
