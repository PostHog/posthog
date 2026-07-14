import api from 'lib/api'

import { createStreamConnection } from './createStreamConnection'

describe('createStreamConnection', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('does not reconnect when abort triggers a delayed stream error', () => {
        const streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined)
        const connection = createStreamConnection({
            url: new URL('https://example.com/events'),
            token: 'token',
            onMessage: jest.fn(),
        })
        const streamOptions = streamSpy.mock.calls[0][1]

        connection.abort()
        streamOptions.onError(new Error('aborted'))
        jest.runAllTimers()

        expect(streamSpy).toHaveBeenCalledTimes(1)
    })

    it('stops the underlying stream retry before scheduling a reconnect', () => {
        const streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined)
        createStreamConnection({
            url: new URL('https://example.com/events'),
            token: 'token',
            onMessage: jest.fn(),
        })
        const streamOptions = streamSpy.mock.calls[0][1]
        const error = new Error('connection lost')

        expect(() => streamOptions.onError(error)).toThrow(error)

        jest.advanceTimersByTime(1000)
        expect(streamSpy).toHaveBeenCalledTimes(2)
    })
})
