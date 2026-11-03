import { describe, expect, test } from 'bun:test'

import { PersonalAPIKey } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { fakeRuntime } from '@/testing'

import { writeLogin } from './stored'

const EU = 'https://eu.posthog.com'
const US = 'https://us.posthog.com'

function login(host: string, apiKey: string): PersonalAPIKey {
    return new PersonalAPIKey({ host, projectId: '42', apiKey })
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
