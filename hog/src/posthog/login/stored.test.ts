import { describe, expect, test } from 'bun:test'

import { PersonalAPIKey } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { parseHost, type Host } from '@/posthog/host'
import { parseProjectId } from '@/posthog/ids'
import { parsePersonalApiKey } from '@/posthog/tokens'
import { fakeRuntime } from '@/testing'

import { writeLogin } from './stored'

const EU = parseHost('https://eu.posthog.com')
const US = parseHost('https://us.posthog.com')

function login(host: Host, apiKey: string): PersonalAPIKey {
    return new PersonalAPIKey({ host, projectId: parseProjectId('42'), apiKey: parsePersonalApiKey(apiKey) })
}

describe('writeLogin', () => {
    test('keeps both logins when two hog processes save logins to different hosts at once', async () => {
        const runtime = fakeRuntime()
        const store = new FileStore(runtime)

        await Promise.all([
            writeLogin(runtime, store, login(EU, 'phx_eu')),
            writeLogin(runtime, store, login(US, 'phx_us')),
        ])

        expect(Object.keys(JSON.parse(runtime.files[store.path] ?? '{}')).sort()).toEqual([EU, US])
        const settings = JSON.parse(runtime.files['/home/test/.config/hog/settings.json'] ?? '{}')
        expect(Object.keys(settings.logins).sort()).toEqual([EU, US])
    })
})
