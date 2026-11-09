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
        const { uuid, ...rest } = parseJSON(mockInternalFetch.mock.calls[0][1].body)
        expect(uuid).toMatch(/^[0-9a-f-]{36}$/)
        mockInternalFetch.mock.calls[0][1].body = JSON.stringify(rest)
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
        expect(parseJSON(mockInternalFetch.mock.calls[0][1].body)).toMatchInlineSnapshot(
            { uuid: expect.any(String) },
            `
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
              "uuid": Any<String>,
            }
        `
        )
    })

    describe('retry', () => {
        const event = { team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' }
        const response = (status: number) => ({
            status,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(''),
            dump: () => Promise.resolve(),
        })
        const sentUuids = (): string[] => mockInternalFetch.mock.calls.map((call) => parseJSON(call[1].body).uuid)

        beforeEach(() => {
            jest.useFakeTimers()
        })
        afterEach(() => {
            jest.useRealTimers()
        })

        it.each([
            ['a socket error', () => mockInternalFetch.mockRejectedValueOnce(new Error('other side closed'))],
            ['a 5xx', () => mockInternalFetch.mockResolvedValueOnce(response(503))],
        ])('retries %s once with the same uuid', async (_name, failFirst) => {
            failFirst()
            const pending = service.capture(event)
            await jest.runAllTimersAsync()
            expect((await pending).status).toBe(200)
            const [first, second, ...rest] = sentUuids()
            expect(rest).toEqual([])
            expect(second).toBe(first)
        })

        it('does not retry a 4xx', async () => {
            mockInternalFetch.mockResolvedValueOnce(response(400))
            expect((await service.capture(event)).status).toBe(400)
            expect(mockInternalFetch).toHaveBeenCalledTimes(1)
        })

        it('throws after the second socket error', async () => {
            mockInternalFetch.mockRejectedValue(new Error('other side closed'))
            const assertion = expect(service.capture(event)).rejects.toThrow('other side closed')
            await jest.runAllTimersAsync()
            await assertion
            expect(mockInternalFetch).toHaveBeenCalledTimes(2)
        })
    })
})
