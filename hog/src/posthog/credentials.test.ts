import { describe, expect, test } from 'bun:test'

import { HogError } from '../core/errors'
import { fakeRuntime } from '../testing'
import { DEFAULT_HOST, resolveCredentials } from './credentials'

const ENV = { POSTHOG_CLI_API_KEY: 'phx_env', POSTHOG_CLI_PROJECT_ID: '1', POSTHOG_CLI_HOST: 'https://env.example.com' }
const DOTENV = 'POSTHOG_CLI_API_KEY="phx_dotenv"\n# comment\nPOSTHOG_CLI_PROJECT_ID=2\n'
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
            'legacy env aliases still work',
            { POSTHOG_CLI_TOKEN: 'phx_old', POSTHOG_CLI_ENV_ID: '9' },
            {},
            undefined,
            undefined,
            'phx_old',
            '9',
            DEFAULT_HOST,
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
            'POSTHOG_HOME moves the credentials file',
            { POSTHOG_HOME: '/custom' },
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
        ['nothing configured', {}, 'not_authenticated'],
        [
            'a key without the phx_ prefix',
            { POSTHOG_CLI_API_KEY: 'abc', POSTHOG_CLI_PROJECT_ID: '1' },
            'invalid_credentials',
        ],
        [
            'a project ID that is not a number',
            { POSTHOG_CLI_API_KEY: 'phx_a', POSTHOG_CLI_PROJECT_ID: 'two' },
            'invalid_credentials',
        ],
    ] as const)('fails on %s', async (_name, env, code) => {
        const error = await resolveCredentials(fakeRuntime({ env }), {}).catch((caught: unknown) => caught)
        expect(error).toBeInstanceOf(HogError)
        expect((error as HogError).code).toBe(code)
    })
})
