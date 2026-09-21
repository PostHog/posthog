import { ApiError, NetworkError } from 'lib/api'

import { isDroppedRequest, loadWithRetry } from './requestRecovery'

describe('requestRecovery', () => {
    it('recognises only the failures the browser produced', () => {
        expect(isDroppedRequest(new NetworkError('network'))).toBe(true)
        expect(isDroppedRequest(new DOMException('Aborted', 'AbortError'))).toBe(true)
        expect(isDroppedRequest(new ApiError('Server error', 500))).toBe(false)
        expect(isDroppedRequest(null)).toBe(false)
    })

    it('repeats a dropped request until it succeeds', async () => {
        const load = jest
            .fn()
            .mockRejectedValueOnce(new NetworkError('network'))
            .mockRejectedValueOnce(new NetworkError('offline'))
            .mockResolvedValue('loaded')

        await expect(loadWithRetry(load)).resolves.toBe('loaded')
        expect(load).toHaveBeenCalledTimes(3)
    })

    it('gives up after three attempts', async () => {
        const load = jest.fn().mockRejectedValue(new NetworkError('network'))

        await expect(loadWithRetry(load)).rejects.toBeInstanceOf(NetworkError)
        expect(load).toHaveBeenCalledTimes(3)
    })

    it('does not repeat a request the server answered', async () => {
        const load = jest.fn().mockRejectedValue(new ApiError('Server error', 500))

        await expect(loadWithRetry(load)).rejects.toBeInstanceOf(ApiError)
        expect(load).toHaveBeenCalledTimes(1)
    })

    it('does not repeat a request a closing page dropped', async () => {
        const load = jest.fn().mockRejectedValue(new NetworkError('navigating'))

        await expect(loadWithRetry(load)).rejects.toBeInstanceOf(NetworkError)
        expect(load).toHaveBeenCalledTimes(1)
    })
})
