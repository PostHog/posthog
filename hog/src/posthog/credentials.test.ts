import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'
import { fakeRuntime } from '@/testing'

import { DEFAULT_HOST, resolveCredentials } from './credentials'

const ENV = { HOG_API_KEY: 'phx_env', HOG_PROJECT_ID: '1', HOG_HOST: 'https://env.example.com' }
const DOTENV = 'HOG_API_KEY="phx_dotenv"\n# comment\nHOG_PROJECT_ID=2\n'
const STORED = JSON.stringify({ token: 'phx_stored', env_id: '3', host: 'https://stored.example.com' })

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
        [
            'a missing dotenv file falls back to the credentials file',
            {},
            { '/home/test/.posthog/credentials.json': STORED },
            '/x/missing.env',
            undefined,
            'phx_stored',
            '3',
            'https://stored.example.com',
        ],
        [
            'the credentials file is last',
            {},
            { '/home/test/.posthog/credentials.json': STORED },
            undefined,
            undefined,
            'phx_stored',
            '3',
            'https://stored.example.com',
        ],
        [
            'HOG_HOME moves the credentials file',
            { HOG_HOME: '/custom' },
            { '/custom/credentials.json': STORED },
            undefined,
            undefined,
            'phx_stored',
            '3',
            'https://stored.example.com',
        ],
        [
            '--host overrides the stored host',
            {},
            { '/home/test/.posthog/credentials.json': STORED },
            undefined,
            'https://flag.example.com',
            'phx_stored',
            '3',
            'https://flag.example.com',
        ],
    ] as const)('%s', async (_name, env, files, dotenvFile, host, apiKey, projectId, expectedHost) => {
        const credentials = await resolveCredentials(fakeRuntime({ env, files }), { dotenvFile, host })
        expect(credentials).toMatchObject({ apiKey, projectId, host: expectedHost })
    })

    test.each([
        ['nothing configured', {}, 'not_authenticated', {}, undefined],
        [
            "posthog-cli's variable names",
            { POSTHOG_CLI_API_KEY: 'phx_a', POSTHOG_CLI_PROJECT_ID: '1' },
            'not_authenticated',
            {},
            undefined,
        ],
        [
            'a key without the phx_ prefix',
            { HOG_API_KEY: 'abc', HOG_PROJECT_ID: '1' },
            'invalid_credentials',
            {},
            undefined,
        ],
        [
            'a project ID that is not a number',
            { HOG_API_KEY: 'phx_a', HOG_PROJECT_ID: 'two' },
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
