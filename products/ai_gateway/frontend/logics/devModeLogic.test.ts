import { cliCallbackUrl, parseCliRequest } from './devModeLogic'

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
