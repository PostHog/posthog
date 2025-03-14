import { LazyLoader } from './lazy-loader'

describe('LazyLoader', () => {
    let loader: jest.Mock
    let lazyLoader: LazyLoader<string>

    beforeEach(() => {
        jest.useFakeTimers()
        loader = jest.fn()
        lazyLoader = new LazyLoader({
            name: 'test',
            loader,
        })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('get', () => {
        it('loads and caches a single value', async () => {
            loader.mockResolvedValue({ key1: 'value1' })

            const result = await lazyLoader.get('key1')
            expect(result).toBe('value1')
            expect(loader).toHaveBeenCalledTimes(1)
            expect(loader).toHaveBeenCalledWith(['key1'])

            // Second call should use cache
            const result2 = await lazyLoader.get('key1')
            expect(result2).toBe('value1')
            expect(loader).toHaveBeenCalledTimes(1)
        })

        it('handles null values', async () => {
            loader.mockResolvedValue({ key1: null })

            const result = await lazyLoader.get('key1')
            expect(result).toBeNull()
        })

        it('handles undefined values', async () => {
            loader.mockResolvedValue({ key1: undefined })

            const result = await lazyLoader.get('key1')
            expect(result).toBeNull()
        })
    })

    describe('getMany', () => {
        it('loads and caches multiple values', async () => {
            loader.mockResolvedValue({ key1: 'value1', key2: 'value2' })

            const result = await lazyLoader.getMany(['key1', 'key2'])
            expect(result).toEqual({ key1: 'value1', key2: 'value2' })
            expect(loader).toHaveBeenCalledTimes(1)
            expect(loader).toHaveBeenCalledWith(['key1', 'key2'])

            // Second call should use cache
            const result2 = await lazyLoader.getMany(['key1', 'key2'])
            expect(result2).toEqual({ key1: 'value1', key2: 'value2' })
            expect(loader).toHaveBeenCalledTimes(1)

            expect(loader).toHaveBeenCalledTimes(1)
        })

        it('handles partial cache hits', async () => {
            loader.mockResolvedValueOnce({ key1: 'value1', key2: 'value2' }).mockResolvedValueOnce({ key3: 'value3' })

            const result = await lazyLoader.getMany(['key1', 'key2'])
            expect(result).toEqual({ key1: 'value1', key2: 'value2' })

            const result2 = await lazyLoader.getMany(['key1', 'key2', 'key3'])
            expect(result2).toEqual({ key1: 'value1', key2: 'value2', key3: 'value3' })
            expect(loader).toHaveBeenCalledTimes(2)
            expect(loader.mock.calls).toMatchInlineSnapshot(`
                [
                  [
                    [
                      "key1",
                      "key2",
                    ],
                  ],
                  [
                    [
                      "key3",
                    ],
                  ],
                ]
            `)
        })
    })

    describe('refresh behavior', () => {
        it('refreshes values after refreshAge', async () => {
            loader.mockResolvedValueOnce({ key1: 'value1' }).mockResolvedValueOnce({ key1: 'value2' })

            await lazyLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(1)

            // Fast forward past refresh age
            jest.advanceTimersByTime(1000 * 60 * 6) // 6 minutes

            await lazyLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(2)
        })

        it('respects custom refreshAge', async () => {
            const customLoader = new LazyLoader({
                name: 'test',
                loader,
                refreshAge: 1000 * 60 * 2, // 2 minutes
            })

            loader.mockResolvedValueOnce({ key1: 'value1' }).mockResolvedValueOnce({ key1: 'value2' })

            await customLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(1)

            // Fast forward past custom refresh age
            jest.advanceTimersByTime(1000 * 60 * 3) // 3 minutes

            await customLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(2)
        })
    })

    describe('error handling', () => {
        it('throws errors by default', async () => {
            loader.mockRejectedValue(new Error('Test error'))

            await expect(lazyLoader.get('key1')).rejects.toThrow('Test error')
        })

        it('handles errors silently when throwOnLoadError is false', async () => {
            const silentLoader = new LazyLoader({
                name: 'test',
                loader,
                throwOnLoadError: false,
            })

            loader.mockRejectedValue(new Error('Test error'))

            const result = await silentLoader.get('key1')
            expect(result).toBeNull()
        })
    })

    describe('markForRefresh', () => {
        it('forces refresh of specified keys', async () => {
            loader.mockResolvedValueOnce({ key1: 'value1' }).mockResolvedValueOnce({ key1: 'value2' })

            await lazyLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(1)

            lazyLoader.markForRefresh('key1')
            await lazyLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(2)
        })

        it('handles multiple keys', async () => {
            loader
                .mockResolvedValueOnce({ key1: 'value1', key2: 'value2' })
                .mockResolvedValueOnce({ key1: 'value3', key2: 'value4' })

            await lazyLoader.getMany(['key1', 'key2'])
            expect(loader).toHaveBeenCalledTimes(1)

            lazyLoader.markForRefresh(['key1', 'key2'])
            await lazyLoader.getMany(['key1', 'key2'])
            expect(loader).toHaveBeenCalledTimes(2)
        })
    })
})
