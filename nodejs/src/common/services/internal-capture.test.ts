import { mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { InternalCaptureService, isTransientNetworkError } from './internal-capture'

const okResponse = {
    status: 200,
    headers: {},
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(''),
    dump: () => Promise.resolve(),
}

describe('InternalCaptureService', () => {
    let service: InternalCaptureService
    beforeEach(() => {
        mockInternalFetch.mockClear()
        mockInternalFetch.mockResolvedValue(okResponse)
        // baseDelayMs 0 keeps the retry backoff instant so the tests don't wait on real timers
        service = new InternalCaptureService(
            { CAPTURE_INTERNAL_URL: 'http://localhost:8010/capture' },
            { maxRetries: 3, baseDelayMs: 0 }
        )
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    })
    it('should capture an event', async () => {
        const res = await service.capture({
            team_token: 'token',
            event: 'event-name',
            distinct_id: 'distinct-id',
            properties: {},
        })
        expect(res.status).toBe(200)
        expect(mockInternalFetch.mock.calls).toMatchInlineSnapshot(
            `
            [
              [
                "http://localhost:8010/capture",
                {
                  "body": "{"api_key":"token","timestamp":"2025-01-01T00:00:00.000Z","distinct_id":"distinct-id","sent_at":"2025-01-01T00:00:00.000Z","event":"event-name","properties":{"capture_internal":true}}",
                  "headers": {
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                },
              ],
            ]
        `
        )
    })

    it('should allow some overrides', async () => {
        await service.capture({
            team_token: 'token',
            event: 'event-name',
            timestamp: '2025-03-03T03:03:03.000Z',
            distinct_id: 'distinct-id',
            properties: {
                capture_internal: false,
                foo: 'bar',
            },
        })
        expect(parseJSON(mockInternalFetch.mock.calls[0][1].body)).toMatchInlineSnapshot(`
            {
              "api_key": "token",
              "distinct_id": "distinct-id",
              "event": "event-name",
              "properties": {
                "capture_internal": true,
                "foo": "bar",
              },
              "sent_at": "2025-01-01T00:00:00.000Z",
              "timestamp": "2025-03-03T03:03:03.000Z",
            }
        `)
    })

    it('retries transient DNS failures with backoff and returns once one succeeds', async () => {
        const transient = Object.assign(new Error('getaddrinfo EAI_AGAIN capture.posthog.svc.cluster.local'), {
            code: 'EAI_AGAIN',
        })
        mockInternalFetch.mockRejectedValueOnce(transient).mockResolvedValueOnce(okResponse)

        const res = await service.capture({ team_token: 'token', event: 'e', distinct_id: 'd' })

        expect(res.status).toBe(200)
        expect(mockInternalFetch).toHaveBeenCalledTimes(2)
    })

    it('gives up and rethrows after exhausting retries on a persistent transient failure', async () => {
        const transient = Object.assign(new Error('boom'), { code: 'ENOTFOUND' })
        mockInternalFetch.mockRejectedValue(transient)

        await expect(service.capture({ team_token: 'token', event: 'e', distinct_id: 'd' })).rejects.toBe(transient)
        // initial attempt + maxRetries
        expect(mockInternalFetch).toHaveBeenCalledTimes(4)
    })

    it('does not retry non-transient failures', async () => {
        const fatal = new Error('500 from capture')
        mockInternalFetch.mockRejectedValue(fatal)

        await expect(service.capture({ team_token: 'token', event: 'e', distinct_id: 'd' })).rejects.toBe(fatal)
        expect(mockInternalFetch).toHaveBeenCalledTimes(1)
    })
})

describe('isTransientNetworkError', () => {
    it.each([
        ['direct EAI_AGAIN code', Object.assign(new Error('x'), { code: 'EAI_AGAIN' }), true],
        ['direct ENOTFOUND code', Object.assign(new Error('x'), { code: 'ENOTFOUND' }), true],
        [
            'code nested in cause chain',
            Object.assign(new Error('fetch failed'), { cause: { code: 'ENOTFOUND' } }),
            true,
        ],
        ['message-only match', new Error('getaddrinfo EAI_AGAIN pgbouncer-cloud-read'), true],
        ['unrelated error', new Error('boom'), false],
        ['other network code', Object.assign(new Error('x'), { code: 'ECONNREFUSED' }), false],
        ['non-error input', 'nope', false],
        ['nullish input', undefined, false],
    ])('classifies %s', (_name, input, expected) => {
        expect(isTransientNetworkError(input)).toBe(expected)
    })
})
