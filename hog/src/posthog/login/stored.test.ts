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

function login(host: Host, apiKey: string, projectId = '42'): PersonalAPIKey {
    return new PersonalAPIKey({ host, projectId: parseProjectId(projectId), apiKey: parsePersonalApiKey(apiKey) })
}

describe('stored logins', () => {
    test('keeps every login when hog processes save logins to other hosts and projects at once', async () => {
        const runtime = fakeRuntime()
        const store = new FileStore(runtime)

        await Promise.all([
            writeLogin(runtime, store, login(EU, 'phx_eu')),
            writeLogin(runtime, store, login(EU, 'phx_eu_7', '7')),
            writeLogin(runtime, store, login(US, 'phx_us')),
        ])

        const credentials = readJson(runtime.files[store.path] ?? '{}', z.record(z.string(), z.unknown()))
        expect(Object.keys(credentials).sort()).toEqual([`${EU}#42`, `${EU}#7`, `${US}#42`])
        const settings = readJson(
            runtime.files['/home/test/.config/hog/settings.json'] ?? '{}',
            z.object({ logins: z.record(z.string(), z.record(z.string(), z.unknown())) })
        )
        expect(Object.fromEntries(Object.entries(settings.logins).map(([host, p]) => [host, Object.keys(p)]))).toEqual({
            [EU]: ['7', '42'],
            [US]: ['42'],
        })
    })

    test('a renewal saves to the store a step-up moved the login to', async () => {
        const runtime = fakeRuntime()
        const file = new FileStore(runtime)
        await writeLogin(runtime, file, login(EU, 'phx_old'))
        const storage = loginStorage(runtime, { key: login(EU, 'phx_old'), store: file })
        await writeLogin(runtime, new KeychainStore(runtime), login(EU, 'phx_stepped_up'))

        await storage.save(login(EU, 'phx_renewed'))

        expect(runtime.keychain[`${EU}#42`]).toContain('phx_renewed')
        expect(runtime.files[file.path] ?? '').not.toContain('phx_renewed')
    })
})
