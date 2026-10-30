import { mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { InternalCaptureService } from './internal-capture'

describe('InternalCaptureService', () => {
    let service: InternalCaptureService
    beforeEach(() => {
        mockInternalFetch.mockClear()
        mockInternalFetch.mockResolvedValue({
            status: 200,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(''),
            dump: () => Promise.resolve(),
        })
        service = new InternalCaptureService({ CAPTURE_INTERNAL_URL: 'http://localhost:8010/capture' })
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
                  "body": "{"api_key":"token","timestamp":"2025-01-01T00:00:00.000Z","distinct_id":"distinct-id","sent_at":"2025-01-01T00:00:00.000Z","event":"event-name","properties":{"$geoip_disable":true,"capture_internal":true}}",
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

    it.each([
        ['a client ip', { $ip: '203.0.113.7' }, { $ip: '203.0.113.7' }],
        ['a caller opt-in', { $geoip_disable: false }, { $geoip_disable: false }],
    ])('leaves geoip to the event when it has %s', async (_name, properties, expected) => {
        await service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id', properties })
        expect(parseJSON(mockInternalFetch.mock.calls[0][1].body).properties).toEqual({
            ...expected,
            capture_internal: true,
        })
    })

    it('captureBatch posts every event of one token in a single array body', async () => {
        const res = await service.captureBatch([
            { team_token: 'token', event: 'one', distinct_id: 'd1' },
            { team_token: 'token', event: 'two', distinct_id: 'd2' },
        ])
        expect(res.status).toBe(200)
        expect(mockInternalFetch).toHaveBeenCalledTimes(1)
        const body = parseJSON(mockInternalFetch.mock.calls[0][1].body)
        expect(body.map((e: any) => [e.api_key, e.event])).toEqual([
            ['token', 'one'],
            ['token', 'two'],
        ])
    })

    it('captureBatch refuses a batch that mixes team tokens', async () => {
        await expect(
            service.captureBatch([
                { team_token: 'token-a', event: 'one', distinct_id: 'd1' },
                { team_token: 'token-b', event: 'two', distinct_id: 'd2' },
            ])
        ).rejects.toThrow('exactly one team_token')
        expect(mockInternalFetch).not.toHaveBeenCalled()
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
                "$geoip_disable": true,
                "capture_internal": true,
                "foo": "bar",
              },
              "sent_at": "2025-01-01T00:00:00.000Z",
              "timestamp": "2025-03-03T03:03:03.000Z",
            }
        `)
    })
})
