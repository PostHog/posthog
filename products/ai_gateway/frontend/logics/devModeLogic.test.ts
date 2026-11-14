import { cliCallbackUrl, parseCliPick, parseCliRequest } from './devModeLogic'

describe('devModeLogic CLI pick', () => {
    test.each([
        ['both values', { cli_cap_usd: '200', cli_ttl_seconds: '259200' }, { capUsd: 200, ttlSeconds: 259200 }],
        ['neither value', {}, { capUsd: null, ttlSeconds: null }],
        ['junk values', { cli_cap_usd: 'lots', cli_ttl_seconds: '1.5' }, { capUsd: null, ttlSeconds: null }],
    ])('parses %s', (_name, params, expected) => {
        expect(parseCliPick(params)).toEqual(expected)
    })
})

const CHALLENGE = 'a'.repeat(43)

describe('devModeLogic CLI handoff', () => {
    test.each([
        ['valid', { cli_challenge: CHALLENGE, cli_port: '53682', cli_state: 's1' }, true],
        ['short challenge', { cli_challenge: 'a'.repeat(42), cli_port: '53682', cli_state: 's1' }, false],
        ['challenge with a slash', { cli_challenge: 'a'.repeat(42) + '/', cli_port: '53682', cli_state: 's1' }, false],
        ['privileged port', { cli_challenge: CHALLENGE, cli_port: '80', cli_state: 's1' }, false],
        ['port out of range', { cli_challenge: CHALLENGE, cli_port: '70000', cli_state: 's1' }, false],
        ['port with a host', { cli_challenge: CHALLENGE, cli_port: '53682@evil.test', cli_state: 's1' }, false],
        ['missing state', { cli_challenge: CHALLENGE, cli_port: '53682' }, false],
    ])('parses a %s request', (_name, params, valid) => {
        expect(parseCliRequest(params) !== null).toBe(valid)
    })

    test('the callback only ever targets the loopback address', () => {
        const request = parseCliRequest({ cli_challenge: CHALLENGE, cli_port: '53682', cli_state: 'x&y' })!
        const url = new URL(cliCallbackUrl(request, 'c0de'))
        expect(url.origin).toBe('http://127.0.0.1:53682')
        expect(url.pathname).toBe('/callback')
        expect(url.searchParams.get('code')).toBe('c0de')
        expect(url.searchParams.get('state')).toBe('x&y')
    })
})
