import { describe, expect, test } from 'bun:test'
import { z } from 'zod'

import type { Runtime } from '@/core/runtime'
import { PersonalAPIKey } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { parseHost, type Host } from '@/posthog/host'
import { parseProjectId } from '@/posthog/ids'
import { readSettings } from '@/posthog/settings'
import { parsePersonalApiKey } from '@/posthog/tokens'
import { fakeRuntime, readJson } from '@/testing'

import { loginStorage, logout, logoutAll, readLogin, writeLogin } from './stored'

const EU = parseHost('https://eu.posthog.com')
const US = parseHost('https://us.posthog.com')
const SETTINGS_FILE = '/home/test/.config/hog/settings.json'

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

    test('a renewal leaves a pending keychain removal to the next login or logout', async () => {
        const runtime = fakeRuntime({ keychain: { [EU]: JSON.stringify({ apiKey: 'phx_left_over' }) } })
        const { secrets } = runtime
        const deleted: string[] = []
        runtime.secrets = {
            ...secrets,
            delete: async (name) => {
                deleted.push(name)
                return secrets.delete(name)
            },
        }
        const record = { store: 'keychain', type: 'personal_api_key', projectId: '42', host: EU }
        const pendingRemovals = [{ store: 'keychain', host: EU, projectId: null }]
        runtime.files[SETTINGS_FILE] = JSON.stringify({ logins: { [EU]: { '42': record } }, pendingRemovals })

        await writeLogin(runtime, new KeychainStore(runtime), login(EU, 'phx_renewed'))

        expect(deleted).toEqual([])
        expect(readJson(runtime.files[SETTINGS_FILE] ?? '{}')).toMatchObject({ pendingRemovals })
    })

    test.each([
        ['logout', (runtime: Runtime) => logout(runtime, { host: EU, projectId: parseProjectId('42') })],
        ['logoutAll', (runtime: Runtime) => logoutAll(runtime)],
    ])('%s removes the copy a move left behind when it failed to save settings.json', async (_, logOut) => {
        const runtime = fakeRuntime({
            files: {
                [SETTINGS_FILE]: JSON.stringify({
                    logins: { [EU]: { store: 'keychain', type: 'personal_api_key', projectId: '42', host: EU } },
                }),
            },
            keychain: { [EU]: JSON.stringify({ apiKey: 'phx_moving' }) },
        })
        const { writePrivateFile } = runtime
        let failed = false
        runtime.writePrivateFile = async (path, contents) => {
            if (path === SETTINGS_FILE && !failed) {
                failed = true
                throw new Error('disk full')
            }
            return writePrivateFile(path, contents)
        }

        await logOut(runtime)

        expect(failed).toBe(true)
        expect(runtime.keychain).toEqual({})
    })

    test('logout revokes an OAuth login when hog cannot save settings.json after removing its secret', async () => {
        const record = {
            store: 'keychain',
            type: 'oauth',
            projectId: '42',
            host: EU,
            expiresAt: Date.UTC(2026, 0, 2),
            scopes: ['openid'],
            loginId: 'login-1',
        }
        const runtime = fakeRuntime({
            files: { [SETTINGS_FILE]: JSON.stringify({ logins: { [EU]: { '42': record } } }) },
            keychain: { [`${EU}#42`]: JSON.stringify({ accessToken: `pha_${'a'.repeat(43)}`, refreshToken: 'phr_1' }) },
            respond: () => ({ status: 200, body: {} }),
        })
        runtime.writePrivateFile = async () => {
            throw new Error('disk full')
        }

        await expect(logout(runtime, { host: EU, projectId: parseProjectId('42') })).rejects.toThrow('disk full')

        expect(runtime.keychain).toEqual({})
        expect(runtime.requests.map((request) => request.url)).toEqual([`${EU}/oauth/revoke/`])
    })

    test('logoutAll keeps a pending removal another hog process adds while it runs', async () => {
        const runtime = fakeRuntime()
        await writeLogin(runtime, new FileStore(runtime), login(EU, 'phx_eu'))
        const added = { store: 'keychain', host: US, projectId: '7' }
        const { secrets } = runtime
        runtime.secrets = {
            ...secrets,
            delete: async (name) => {
                const settings = readJson(runtime.files[SETTINGS_FILE] ?? '{}', z.looseObject({}))
                runtime.files[SETTINGS_FILE] = JSON.stringify({ ...settings, pendingRemovals: [added] })
                return secrets.delete(name)
            },
        }

        await logoutAll(runtime)

        expect(readJson(runtime.files[SETTINGS_FILE] ?? '{}')).toMatchObject({ pendingRemovals: [added] })
    })

    test('a login in the old shape stays readable when hog cannot write to its folder', async () => {
        const runtime = fakeRuntime({
            files: {
                [SETTINGS_FILE]: JSON.stringify({
                    logins: { [EU]: { store: 'file', type: 'personal_api_key', projectId: '42', host: EU } },
                    host: EU,
                }),
                '/home/test/.config/hog/credentials.json': JSON.stringify({ [EU]: { apiKey: 'phx_read_only' } }),
            },
        })
        const readOnly = Object.assign(new Error('read-only file system'), { code: 'EROFS' })
        runtime.createFile = async () => {
            throw readOnly
        }
        runtime.writePrivateFile = async () => {
            throw readOnly
        }

        const settings = await readSettings(runtime)
        const login = await readLogin(runtime, settings, { host: EU, projectId: parseProjectId('42') })

        expect(login?.key).toMatchObject({ apiKey: 'phx_read_only' })
    })
})
