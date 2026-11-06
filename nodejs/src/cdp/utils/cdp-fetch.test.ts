import { logger } from '~/common/utils/logger'
import { fetch } from '~/common/utils/request'

import { cdpTrackedFetch, fetchErrorDetail } from './cdp-fetch'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    fetch: jest.fn(),
}))

describe('cdp-fetch', () => {
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

    describe('cdpTrackedFetch', () => {
        it('keeps a token in the URL out of the logs when the connection resets', async () => {
            const connectionReset = Object.assign(new Error('socket hang up'), { code: 'ECONNRESET' })
            jest.mocked(fetch).mockRejectedValue(connectionReset)
            const warn = jest.spyOn(logger, 'warn')

            await cdpTrackedFetch({
                url: 'https://relay.example.com/v1/hooks/endpoint-key/hook-id/url-token',
                fetchParams: { method: 'POST' },
                templateId: 'template-t3-code',
            })

            expect(warn).toHaveBeenCalled()
            expect(JSON.stringify(warn.mock.calls)).not.toContain('url-token')
            expect(JSON.stringify(warn.mock.calls)).toContain('relay.example.com')
        })
    })
})
