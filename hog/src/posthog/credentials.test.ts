import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'
import { fakeRuntime } from '@/testing'

import { DEFAULT_HOST, resolveCredentials } from './credentials'

const ENV = { HOG_PERSONAL_API_KEY: 'phx_env', HOG_PROJECT_ID: '1', HOG_HOST: 'https://env.example.com' }
const DOTENV = 'HOG_PERSONAL_API_KEY="phx_dotenv"\n# comment\nHOG_PROJECT_ID=2\n'
const STORED = JSON.stringify({ token: 'phx_stored', env_id: '3', host: 'https://stored.example.com' })
const LEGACY_CLI_FILE = '/home/test/.posthog/credentials.json'
const SETTINGS_FILE = '/home/test/.config/hog/settings.json'
const EU = 'https://eu.posthog.com'
const US = 'https://us.posthog.com'

// What the store keeps for a login: only its secret.
function login(apiKey: string): string {
    return JSON.stringify({ apiKey })
}

// `host` is the last login. `stores` says where the login for each host is.
function settings(host: string, stores: Record<string, 'keychain' | 'file'>): Record<string, string> {
    const logins = Object.fromEntries(
        Object.entries(stores).map(([login, store]) => [login, { store, type: 'personal_api_key', projectId: '9' }])
    )
    return { [SETTINGS_FILE]: JSON.stringify({ logins, host }) }
}

describe('resolveCredentials', () => {
    test.each([
        [
            'the process env comes first',
            ENV,
            { '/x/.env': DOTENV },
            '/x/.env',
            undefined,
            'phx_env',
            '1',
            'https://env.example.com',
        ],
        [
            'the dotenv file is next',
            {},
            { '/x/.env': DOTENV, '/home/test/.posthog/credentials.json': STORED },
            '/x/.env',
            undefined,
            'phx_dotenv',
            '2',
            DEFAULT_HOST,
        ],
    ] as const)('%s', async (_name, env, files, dotenvFile, host, apiKey, projectId, expectedHost) => {
        const credentials = await resolveCredentials(fakeRuntime({ env, files }), { dotenvFile, host })
        expect(credentials).toMatchObject({ token: apiKey, projectId, host: expectedHost })
    })

    test.each([
        ['nothing configured', {}, 'not_authenticated', {}, undefined],
        // `hog auth migrate` is the only command that reads posthog-cli's file.
        ["only posthog-cli's credentials file", {}, 'not_authenticated', { [LEGACY_CLI_FILE]: STORED }, undefined],
        [
            "a missing dotenv file with only posthog-cli's credentials file",
            {},
            'not_authenticated',
            { [LEGACY_CLI_FILE]: STORED },
            '/x/missing.env',
        ],
        [
            "posthog-cli's variable names",
            { POSTHOG_CLI_API_KEY: 'phx_a', POSTHOG_CLI_PROJECT_ID: '1' },
            'not_authenticated',
            {},
            undefined,
        ],
        [
            'a key without the phx_ prefix',
            { HOG_PERSONAL_API_KEY: 'abc', HOG_PROJECT_ID: '1' },
            'invalid_credentials',
            {},
            undefined,
        ],
        [
            'a project ID that is not a number',
            { HOG_PERSONAL_API_KEY: 'phx_a', HOG_PROJECT_ID: 'two' },
            'invalid_credentials',
            {},
            undefined,
        ],
        [
            'a dotenv file without the credentials',
            {},
            'not_authenticated',
            { '/x/.env': 'OTHER=1\n', '/home/test/.posthog/credentials.json': STORED },
            '/x/.env',
        ],
    ] as const)('fails on %s', async (_name, env, code, files: Record<string, string>, dotenvFile) => {
        const error = await resolveCredentials(fakeRuntime({ env, files }), { dotenvFile }).catch(
            (caught: unknown) => caught
        )
        expect(error).toBeInstanceOf(HogError)
        expect((error as HogError).code).toBe(code)
    })

    test.each([
        [
            'a hog login',
            settings(EU, { [EU]: 'keychain' }),
            { [EU]: login('phx_eu') },
            {},
            { token: 'phx_eu', host: EU, source: 'store', store: 'keychain' },
        ],
        [
            'posthog.json picks the stored login for its host',
            settings(US, { [EU]: 'keychain', [US]: 'keychain' }),
            { [EU]: login('phx_eu'), [US]: login('phx_us') },
            { configHost: `${EU}/` },
            { token: 'phx_eu', host: EU },
        ],
        [
            '--host picks the stored login for that host',
            settings(US, { [EU]: 'keychain', [US]: 'keychain' }),
            { [EU]: login('phx_eu'), [US]: login('phx_us') },
            { host: EU },
            { token: 'phx_eu', host: EU },
        ],
        [
            'a later file login to another host keeps the keychain login',
            settings(US, { [EU]: 'keychain', [US]: 'file' }),
            { [EU]: login('phx_eu') },
            { configHost: EU },
            { token: 'phx_eu', host: EU, store: 'keychain' },
        ],
        [
            'a login in the file store',
            {
                ...settings(EU, { [EU]: 'file' }),
                '/home/test/.config/hog/credentials.json': JSON.stringify({ [EU]: JSON.parse(login('phx_file')) }),
            },
            {},
            {},
            { token: 'phx_file', source: 'store', store: 'file', path: '/home/test/.config/hog/credentials.json' },
        ],
        [
            'a posthog.json host without a login of its own',
            settings(US, { [US]: 'keychain' }),
            { [US]: login('phx_us') },
            { configHost: EU },
            'host_mismatch',
        ],
    ] as const)('%s', async (_name, files, keychain, options, expected) => {
        const outcome = await resolveCredentials(fakeRuntime({ files, keychain }), options).catch((error: unknown) =>
            error instanceof HogError ? error.code : error
        )
        if (typeof expected === 'string') {
            expect(outcome).toBe(expected)
        } else {
            expect(outcome).toMatchObject(expected)
        }
    })

    test('fails on a dotenv file it cannot read, instead of falling back', async () => {
        const runtime = fakeRuntime({ files: { '/home/test/.posthog/credentials.json': STORED } })
        runtime.readFile = async (path) => {
            if (path === '/x/.env') {
                throw Object.assign(new Error('EACCES: permission denied'), { code: 'EACCES' })
            }
            return STORED
        }
        const error = await resolveCredentials(runtime, { dotenvFile: '/x/.env' }).catch((caught: unknown) => caught)
        expect((error as HogError).code).toBe('invalid_dotenv_file')
    })
})
