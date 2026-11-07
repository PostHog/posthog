import { describe, expect, test } from 'bun:test'
import { z } from 'zod'

import { PersonalAPIKey } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { parseHost, type Host } from '@/posthog/host'
import { parseProjectId } from '@/posthog/ids'
import { parsePersonalApiKey } from '@/posthog/tokens'
import { fakeRuntime, readJson } from '@/testing'

import { loginStorage, writeLogin } from './stored'

const EU = parseHost('https://eu.posthog.com')
const US = parseHost('https://us.posthog.com')

function login(host: Host, apiKey: string): PersonalAPIKey {
    return new PersonalAPIKey({ host, projectId: parseProjectId('42'), apiKey: parsePersonalApiKey(apiKey) })
}

describe('stored logins', () => {
    test('keeps both logins when two hog processes save logins to different hosts at once', async () => {
        const runtime = fakeRuntime()
        const store = new FileStore(runtime)

        await Promise.all([
            writeLogin(runtime, store, login(EU, 'phx_eu')),
            writeLogin(runtime, store, login(US, 'phx_us')),
        ])

        const credentials = readJson(runtime.files[store.path] ?? '{}', z.record(z.string(), z.unknown()))
        expect(Object.keys(credentials).sort()).toEqual([EU, US])
        const settings = readJson(
            runtime.files['/home/test/.config/hog/settings.json'] ?? '{}',
            z.object({ logins: z.record(z.string(), z.unknown()) })
        )
        expect(Object.keys(settings.logins).sort()).toEqual([EU, US])
    })

    test('a renewal saves to the store a step-up moved the login to', async () => {
        const runtime = fakeRuntime()
        const file = new FileStore(runtime)
        await writeLogin(runtime, file, login(EU, 'phx_old'))
        const storage = loginStorage(runtime, { key: login(EU, 'phx_old'), store: file })
        await writeLogin(runtime, new KeychainStore(runtime), login(EU, 'phx_stepped_up'))

        await storage.save(login(EU, 'phx_renewed'))

        expect(runtime.keychain[EU]).toContain('phx_renewed')
        expect(runtime.files[file.path] ?? '').not.toContain('phx_renewed')
    })
})
