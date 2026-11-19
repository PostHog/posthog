import { describe, expect, test } from 'bun:test'

import { HogError } from '@/core/errors'

import { parseHost } from './host'
import { parseOrganizationId, parseProjectId } from './ids'
import { parseOAuthAccessToken, parsePersonalApiKey, parseProjectToken, parseWorkloadToken } from './tokens'

function errorOf(parse: () => unknown): string {
    try {
        parse()
    } catch (error) {
        return error instanceof HogError ? `${error.code}: ${error.message}` : String(error)
    }
    return 'parsed'
}

describe('brand factories', () => {
    test.each([
        ['a personal API key', () => parsePersonalApiKey('phx_abc123'), 'parsed'],
        [
            'an OAuth access token as a personal API key',
            () => parsePersonalApiKey('pha_abc123'),
            'invalid_personal_api_key: This is an OAuth access token, not a personal API key, which must start with phx_.',
        ],
        [
            'a legacy personal API key without a prefix',
            () => parsePersonalApiKey('a'.repeat(43)),
            "invalid_personal_api_key: This doesn't look like a personal API key: it must start with phx_.",
        ],
        [
            'a personal API key copied with a line break',
            () => parsePersonalApiKey('phx_abc\n'),
            "invalid_personal_api_key: This token is cut off, or has characters a token can't have, such as a space or a quote. Copy it again.",
        ],
        [
            'a personal API key as an OAuth access token',
            () => parseOAuthAccessToken('phx_abc123'),
            'invalid_oauth_access_token: This is a personal API key, not an OAuth access token, which must start with pha_.',
        ],
        ['a JWT as a workload token', () => parseWorkloadToken('eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl'), 'parsed'],
        [
            'a personal API key as a workload token',
            () => parseWorkloadToken('phx_abc123'),
            'invalid_workload_token: This is a personal API key, not a workload token, which must be a JWT, three parts joined by dots.',
        ],
        ['a custom project token without the prefix', () => parseProjectToken('my-team-token'), 'parsed'],
        ['a custom project token with the prefix and punctuation', () => parseProjectToken('phc_team.v1'), 'parsed'],
        [
            'a personal API key as a project token',
            () => parseProjectToken('phx_abc123'),
            'invalid_project_token: This is a personal API key, not a project token.',
        ],
        [
            'an organization ID that is not a UUID',
            () => parseOrganizationId('acme'),
            "invalid_organization_id: The organization ID must be a UUID. Pass the organization's UUID, like 0188f5b4-1d2a-7000-8a1c-3f6e2b9c7d10.",
        ],
        [
            'a project ID that is not a number',
            () => parseProjectId('two', { code: 'invalid_credentials' }),
            'invalid_credentials: The project ID must be a number. Pass a numeric project ID, like 12345.',
        ],
        [
            'a host with a password in it',
            () => parseHost('https://user:secret@eu.posthog.com'),
            'invalid_host: The host must not have a user name or password in it.',
        ],
        [
            'a host without a scheme',
            () => parseHost('localhost:8000'),
            'invalid_host: The host must start with https:// or http://, like https://us.posthog.com.',
        ],
        [
            'a host that is not a URL, without repeating its password',
            () => parseHost('https://user:secret@ph example.com'),
            'invalid_host: The host must be a URL, like https://us.posthog.com.',
        ],
        [
            'a host with a query',
            () => parseHost('https://eu.posthog.com/?token=secret'),
            'invalid_host: The host must not have a query (?) or a fragment (#) in it.',
        ],
    ])('%s', (_name, parse, expected) => {
        expect(errorOf(parse)).toBe(expected)
    })

    test.each([
        ['HTTPS://EU.posthog.com:443/', 'https://eu.posthog.com'],
        ['https://example.com/posthog/', 'https://example.com/posthog'],
    ])('the host %s is the same login as %s', (raw, expected) => {
        expect(parseHost(raw)).toBe(parseHost(expected))
    })
})
