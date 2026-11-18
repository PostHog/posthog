import { gzipSync } from 'zlib'

import {
    RequestParsingError,
    UnspecifiedCompressionFallbackParsingError,
    decodeRequest,
    decompress,
} from './request-decoding'

describe('request decoding', () => {
    const json = '{"api_key":"phc_x","app_id":"a"}'
    const parsed = { api_key: 'phc_x', app_id: 'a' }

    describe('decompress', () => {
        it.each([
            ['a plain body', Buffer.from(json), ''],
            ['a gzipped body', gzipSync(Buffer.from(json)), 'gzip'],
            ['a body gzipped by posthog-js', gzipSync(Buffer.from(json)), 'gzip-js'],
            ['a gzipped body that did not say so', gzipSync(Buffer.from(json)), ''],
            ['a base64 body', Buffer.from(Buffer.from(json).toString('base64')), ''],
            ['a base64 body in the data= form', Buffer.from(`data=${Buffer.from(json).toString('base64')}`), ''],
        ])('reads %s', (_name, body, compression) => {
            expect(decompress(body, compression)).toEqual(parsed)
        })

        it.each([
            ['an empty body', Buffer.alloc(0), ''],
            ['a zero-length string', '', ''],
        ])('returns null for %s', (_name, body, compression) => {
            expect(decompress(body, compression)).toBeNull()
        })

        it('rejects the literal string undefined, which a broken client sends as a gzip body', () => {
            expect(() => decompress(Buffer.from('undefined'), 'gzip')).toThrow(RequestParsingError)
        })

        it('rejects a truncated gzip stream', () => {
            expect(() => decompress(gzipSync(Buffer.from(json)).subarray(0, 10), 'gzip')).toThrow(RequestParsingError)
        })

        it('reports an undeclared body that is neither JSON nor gzip separately', () => {
            // Django distinguishes this case, so the two error types are kept apart here even though
            // the endpoint answers both the same way.
            expect(() => decompress(Buffer.from('not json at all'), '')).toThrow(
                UnspecifiedCompressionFallbackParsingError
            )
        })

        it('rejects lz64, which nothing that registers a device sends', () => {
            expect(() => decompress(Buffer.from('anything'), 'lz64')).toThrow(RequestParsingError)
        })

        it('rejects bytes that are not valid UTF-8 rather than substituting characters', () => {
            expect(() => decompress(Buffer.from([0x7b, 0xff, 0xfe, 0x7d]), '')).toThrow(
                UnspecifiedCompressionFallbackParsingError
            )
        })

        it.each([
            ['NaN', '{"value": NaN}', { value: null }],
            ['Infinity', '{"value": Infinity}', { value: null }],
            ['-Infinity', '{"value": -Infinity}', { value: null }],
            ['several at once', '{"a":NaN,"bb":[Infinity,-Infinity]}', { a: null, bb: [null, null] }],
        ])('maps the bare constant %s to null, as python does', (_name, body, expected) => {
            expect(decompress(Buffer.from(body), '')).toEqual(expected)
        })

        it('destroys a short body whose base64 attempt happens to succeed, as django does', () => {
            // `{"a":NaN}` holds four base64-alphabet characters, so Django's unconditional base64
            // attempt decodes it to noise and never reaches the JSON parse. Verified against the
            // Django implementation, which raises on this body too. Matching it matters more than
            // improving on it: the two have to answer the same request the same way.
            expect(() => decompress(Buffer.from('{"a":NaN}'), '')).toThrow(UnspecifiedCompressionFallbackParsingError)
        })

        it('leaves those words alone inside a string', () => {
            expect(decompress(Buffer.from('{"a":"NaN and Infinity"}'), '')).toEqual({ a: 'NaN and Infinity' })
        })

        it('leaves an escaped quote in a string from breaking the constant scan', () => {
            expect(decompress(Buffer.from('{"a":"quote \\" NaN","b":NaN}'), '')).toEqual({
                a: 'quote " NaN',
                b: null,
            })
        })
    })

    describe('decodeRequest', () => {
        it('reads the compression named in the query string for POST', () => {
            const result = decodeRequest({
                method: 'POST',
                body: gzipSync(Buffer.from(json)),
                query: new URLSearchParams('compression=gzip'),
            })

            expect(result.data).toEqual(parsed)
        })

        it('reads a urlencoded form body', () => {
            const form = new URLSearchParams({ api_key: 'phc_form', data: json })

            const result = decodeRequest({
                method: 'POST',
                body: Buffer.from(form.toString()),
                contentType: 'application/x-www-form-urlencoded',
            })

            expect(result.data).toEqual(parsed)
            expect(result.form?.get('api_key')).toEqual('phc_form')
        })

        it('ignores the charset parameter on the content type', () => {
            const result = decodeRequest({
                method: 'POST',
                body: Buffer.from(json),
                contentType: 'application/json; charset=utf-8',
            })

            expect(result.data).toEqual(parsed)
        })

        it('reads the body of a DELETE, which is how every SDK unregisters a device', () => {
            const result = decodeRequest({ method: 'DELETE', body: Buffer.from(json) })

            expect(result.data).toEqual(parsed)
        })

        it('reads a gzipped DELETE body from the content-encoding header', () => {
            const result = decodeRequest({
                method: 'DELETE',
                body: gzipSync(Buffer.from(json)),
                contentEncoding: 'gzip',
            })

            expect(result.data).toEqual(parsed)
        })
    })
})
