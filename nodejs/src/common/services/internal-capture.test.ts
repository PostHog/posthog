import { mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { InternalCaptureError, InternalCaptureService, isRemoteOriginError } from './internal-capture'

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
        ).rejects.toThrow(InternalCaptureError)

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

    // The wrapper has to keep the rejection reachable as `cause`, because that is what callers
    // classify to decide whether the failure is worth an exception.
    it.each([
        {
            name: 'a timeout',
            rejection: Object.assign(new Error('aborted'), { name: 'TimeoutError' }),
            detail: 'aborted',
            remoteOrigin: true,
        },
        {
            name: 'a refused connection',
            rejection: Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' }),
            detail: 'connect ECONNREFUSED',
            remoteOrigin: true,
        },
        { name: 'an unexpected failure', rejection: new Error('boom'), detail: 'boom', remoteOrigin: false },
    ])('wraps $name with the caller and the target url', async ({ rejection, detail, remoteOrigin }) => {
        mockInternalFetch.mockRejectedValue(rejection)

        const thrown = await service
            .capture({ team_token: 'token', event: 'event-name', distinct_id: 'distinct-id' }, 'caller-name')
            .catch((error: unknown) => error)

        expect(thrown).toMatchObject({
            name: 'InternalCaptureError',
            caller: 'caller-name',
            url: 'http://localhost:8010/capture',
            cause: rejection,
            message: `Internal capture from caller-name to http://localhost:8010/capture failed: ${detail}`,
        })
        expect(isRemoteOriginError(thrown)).toBe(remoteOrigin)
    })
})
