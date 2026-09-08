import { mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

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
        const res = await service.capture(
            {
                team_token: 'token',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: {},
            },
            'test'
        )
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
        await service.capture(
            {
                team_token: 'token',
                event: 'event-name',
                timestamp: '2025-03-03T03:03:03.000Z',
                distinct_id: 'distinct-id',
                properties: {
                    capture_internal: false,
                    foo: 'bar',
                },
            },
            'test'
        )
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

    // A suppressed remote-origin failure leaves this log as the only per-failure record, and pino
    // drops name, message, and stack from a raw error under a key it does not serialize.
    it('logs the failure with the error name, message, and stack', async () => {
        const loggerErrorSpy = jest.spyOn(logger, 'error').mockImplementation(() => {})
        mockInternalFetch.mockRejectedValue(
            Object.assign(new Error('The operation was aborted due to timeout'), { name: 'TimeoutError' })
        )

        await expect(
            service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' }, 'caller-name')
        ).rejects.toThrow()

        expect(loggerErrorSpy).toHaveBeenCalledWith('Error capturing internal event', {
            error: {
                name: 'TimeoutError',
                message: 'The operation was aborted due to timeout',
                stack: expect.any(String),
            },
            caller: 'caller-name',
        })
        loggerErrorSpy.mockRestore()
    })

    it('wraps a failure with the caller and the target url', async () => {
        mockInternalFetch.mockRejectedValue(new Error('connect ECONNREFUSED'))

        await expect(
            service.capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' }, 'caller-name')
        ).rejects.toMatchObject({
            name: 'InternalCaptureError',
            caller: 'caller-name',
            url: 'http://localhost:8010/capture',
            message: 'Internal capture from caller-name to http://localhost:8010/capture failed: connect ECONNREFUSED',
        })
    })
})
