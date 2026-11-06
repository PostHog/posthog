import { describe, expect, test } from 'bun:test'

import { challengedScopes } from './step-up'

describe('challengedScopes', () => {
    test.each([
        ['another error', 'Bearer error="invalid_token", scope="insight:read"', undefined],
        // hog puts these scopes into a command an agent runs, so only scope names get through.
        [
            'text that is not a scope name',
            'Bearer error="insufficient_scope", scope="insight:read $(curl\\ example.com) query:admin"',
            ['insight:read'],
        ],
    ])('%s', (_name, header, expected) => {
        expect(challengedScopes(header)).toEqual(expected)
    })
})
