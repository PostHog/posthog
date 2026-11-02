import { describe, expect, test } from 'bun:test'

import { fakeRuntime } from '@/testing'

import { PersonalApiKey } from './credential'
import { FileStore } from './credential-store'
import { writeLogin } from './logins'

const EU = 'https://eu.posthog.com'
const US = 'https://us.posthog.com'

function login(host: string, apiKey: string): PersonalApiKey {
    return new PersonalApiKey(host, '42', apiKey)
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
