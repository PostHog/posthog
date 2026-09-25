import { mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { InternalCaptureService } from './internal-capture'

const okResponse = () => ({
    status: 200,
    headers: {},
    json: () => Promise.resolve({}),
    text: () => Promise.resolve(''),
    dump: () => Promise.resolve(),
})

const responseWithStatus = (status: number) => ({ ...okResponse(), status })

describe('InternalCaptureService', () => {
    let service: InternalCaptureService
    beforeEach(() => {
        mockInternalFetch.mockClear()
        mockInternalFetch.mockResolvedValue(okResponse())
        service = new InternalCaptureService({ CAPTURE_INTERNAL_URL: 'http://localhost:8010/capture' })
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    })
    it('should capture an event', async () => {
        await service.capture({
            team_token: 'token',
            event: 'event-name',
            distinct_id: 'distinct-id',
            properties: {},
        })
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

    const connectTimeout = (): Error =>
        Object.assign(new Error('Connect Timeout Error'), { code: 'UND_ERR_CONNECT_TIMEOUT' })

    it('retries a connect timeout and keeps the event', async () => {
        mockInternalFetch.mockRejectedValueOnce(connectTimeout())

        await service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' })

        expect(mockInternalFetch).toHaveBeenCalledTimes(2)
    })

    it('gives up after the last retry so the caller sees the loss', async () => {
        mockInternalFetch.mockRejectedValue(connectTimeout())

        await expect(
            service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' })
        ).rejects.toThrow('Connect Timeout Error')
        expect(mockInternalFetch).toHaveBeenCalledTimes(3)
    })

    it('retries a 503 from capture', async () => {
        mockInternalFetch.mockResolvedValueOnce(responseWithStatus(503))

        await service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' })

        expect(mockInternalFetch).toHaveBeenCalledTimes(2)
    })

    it('does not retry a rejected event', async () => {
        mockInternalFetch.mockResolvedValue(responseWithStatus(401))

        await expect(
            service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' })
        ).rejects.toThrow('rejected the event with status 401')
        expect(mockInternalFetch).toHaveBeenCalledTimes(1)
    })

    it('drains the response body so the socket returns to the pool', async () => {
        const dump = jest.fn(() => Promise.resolve())
        mockInternalFetch.mockResolvedValue({ ...okResponse(), dump })

        await service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' })

        expect(dump).toHaveBeenCalledTimes(1)
    })
})
