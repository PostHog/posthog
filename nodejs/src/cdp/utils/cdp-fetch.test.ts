import '~/tests/helpers/mocks/request.mock'

import { cdpTrackedFetch, fetchErrorDetail, recordRequestOrigins } from './cdp-fetch'

describe('fetchErrorDetail', () => {
    // Guards the unpacking of AggregateError causes: undici throws it with an empty message when
    // every connection attempt fails, so falling back to `error.message` alone would turn a
    // diagnosable per-address failure back into an opaque "AggregateError: ".
    it.each([
        [
            'a plain error keeps its message',
            new Error('connect ETIMEDOUT 10.0.0.1:443'),
            'connect ETIMEDOUT 10.0.0.1:443',
        ],
        [
            'an empty-message AggregateError surfaces its causes',
            new AggregateError([
                new Error('connect ECONNREFUSED 1.2.3.4:443'),
                new Error('connect ENETUNREACH ::1:443'),
            ]),
            'connect ECONNREFUSED 1.2.3.4:443; connect ENETUNREACH ::1:443',
        ],
        [
            'an AggregateError with a message appends its causes',
            new AggregateError([new Error('boom')], 'All attempts failed'),
            'All attempts failed (boom)',
        ],
        ['an AggregateError with no causes and no message stays empty', new AggregateError([]), ''],
    ])('%s', (_name, error, expected) => {
        expect(fetchErrorDetail(error)).toBe(expected)
    })
})

describe('recordRequestOrigins', () => {
    const send = (url: string) => cdpTrackedFetch({ url, fetchParams: { method: 'POST' }, templateId: 'template-test' })

    it('records each origin once, without the credentials, path or query of the URL', async () => {
        const origins = new Set<string>()

        await recordRequestOrigins(origins, async () => {
            await send('https://user:secret@example.com/hook?token=abc')
            await send('https://example.com/other')
            await send('http://localhost:8080/path')
        })

        expect([...origins].sort()).toEqual(['http://localhost:8080', 'https://example.com'])
    })

    it('records nothing for a request sent outside a recording', async () => {
        const origins = new Set<string>()
        await recordRequestOrigins(origins, () => Promise.resolve())

        await send('https://example.com/hook')

        expect([...origins]).toEqual([])
    })
})
