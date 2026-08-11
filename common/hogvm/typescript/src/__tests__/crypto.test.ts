import crypto from 'crypto'

import { sha1, sha1HmacChain } from '../stl/crypto'
import { STL } from '../stl/stl'
import { ExecOptions } from '../types'

describe('sha1 and sha1HmacChain', () => {
    const options: ExecOptions = { external: { crypto } }

    describe('sha1', () => {
        test.each([
            ['', 'hex', 'da39a3ee5e6b4b0d3255bfef95601890afd80709'],
            ['abc', 'hex', 'a9993e364706816aba3e25717850c26c9cd0d89d'],
            ['hello', 'hex', 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d'],
            ['abc', 'base64', 'qZk+NkcGgWq6PiVxeFDCbJzQ2J0='],
            ['abc', 'base64url', 'qZk-NkcGgWq6PiVxeFDCbJzQ2J0'],
        ] as const)('sha1(%p, %p)', (data, encoding, expected) => {
            expect(sha1(data, encoding, options)).toBe(expected)
        })

        test('defaults to hex', () => {
            expect(sha1('abc', undefined, options)).toBe(sha1('abc', 'hex', options))
        })

        test('passes null through', () => {
            expect(sha1(null, 'hex', options)).toBeNull()
        })

        test('binary encoding holds the raw digest', () => {
            const binary = sha1('abc', 'binary', options) as string
            expect(Buffer.from(binary, 'binary').toString('hex')).toBe(sha1('abc', 'hex', options))
        })

        test('throws without the crypto module', () => {
            expect(() => sha1('abc', 'hex', {})).toThrow('The crypto module is required for "sha1Hex" to work.')
        })
    })

    describe('sha1HmacChain', () => {
        // RFC 2202 HMAC-SHA1 test vectors, limited to the cases whose key and message are text.
        // A two-element chain is a plain HMAC of key and message.
        test.each([
            ['\x0b'.repeat(20), 'Hi There', 'b617318655057264e28bc0b6fb378c8ef146be00'],
            ['Jefe', 'what do ya want for nothing?', 'effcdf6ae5eb2fa2d27416d5f184df9c259a7c79'],
            ['\x0c'.repeat(20), 'Test With Truncation', '4c1a03424b55e07fe7f27be1d58bb9324a9a5a04'],
        ])('matches RFC 2202 for %p', (key, message, expected) => {
            expect(sha1HmacChain([key, message], 'hex', options)).toBe(expected)
        })

        test('rekeys with the previous raw digest', () => {
            const key = crypto.createHmac('sha1', '1').update('string').digest()
            const expected = crypto.createHmac('sha1', key).update('more').digest('hex')
            expect(sha1HmacChain(['1', 'string', 'more'], 'hex', options)).toBe(expected)
        })

        test.each([
            ['hex', 'e559ff0c3fc9c9e13a5b5d78fcd722b4f7ec6a9a'],
            ['base64', '5Vn/DD/JyeE6W114/NcitPfsapo='],
            ['base64url', '5Vn_DD_JyeE6W114_NcitPfsapo'],
        ] as const)('encodes as %p', (encoding, expected) => {
            expect(sha1HmacChain(['1', 'string', 'more', 'keys'], encoding, options)).toBe(expected)
        })

        test('rejects fewer than two elements', () => {
            expect(() => sha1HmacChain(['only-a-key'], 'hex', options)).toThrow(
                'Data array must contain at least two elements.'
            )
        })
    })

    describe('STL registration', () => {
        test.each([
            ['sha1Hex', ['abc'], 'a9993e364706816aba3e25717850c26c9cd0d89d'],
            ['sha1', ['abc', 'base64'], 'qZk+NkcGgWq6PiVxeFDCbJzQ2J0='],
            [
                'sha1HmacChainHex',
                [['Jefe', 'what do ya want for nothing?']],
                'effcdf6ae5eb2fa2d27416d5f184df9c259a7c79',
            ],
            [
                'sha1HmacChain',
                [['Jefe', 'what do ya want for nothing?'], 'hex'],
                'effcdf6ae5eb2fa2d27416d5f184df9c259a7c79',
            ],
        ])('%p is callable through the STL', (name, args, expected) => {
            expect(STL[name].fn(args, name, options)).toBe(expected)
        })
    })
})
