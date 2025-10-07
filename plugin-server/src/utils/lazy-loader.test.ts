import { LazyLoader } from './lazy-loader'
import { delay } from './utils'

describe('LazyLoader', () => {
    jest.setTimeout(1000)

    let loader: jest.Mock
    let lazyLoader: LazyLoader<string>
    let start: number

    beforeEach(() => {
        start = Date.now()
        jest.spyOn(Date, 'now').mockReturnValue(start)
        loader = jest.fn()
        lazyLoader = new LazyLoader({
            name: 'test',
            loader,
        })
    })

    afterEach(() => {
        jest.spyOn(Date, 'now').mockRestore()
    })

    describe('constructor', () => {
        it('should throw if refreshBackgroundAgeMs is greater than refreshAgeMs', () => {
            expect(
                () =>
                    new LazyLoader({
                        name: 'test',
                        loader,
                        refreshAgeMs: 1000 * 60 * 2,
                        refreshBackgroundAgeMs: 1000 * 60 * 3,
                    })
            ).toThrow('refreshBackgroundAgeMs must be smaller than refreshAgeMs')
        })

        it('should set defaults if not provided', () => {
            const lazyLoader = new LazyLoader({
                name: 'test',
                loader,
            })

            expect(lazyLoader['refreshAgeMs']).toBe(300000)
            expect(lazyLoader['refreshNullAgeMs']).toBe(300000)
            expect(lazyLoader['refreshBackgroundAgeMs']).toBe(undefined)
            expect(lazyLoader['refreshJitterMs']).toBe(60000)
        })

        it('should derive values based on refreshAgeMs', () => {
            const refreshAgeMs = 1000 * 60 * 2
            const lazyLoader = new LazyLoader({
                name: 'test',
                loader,
                refreshAgeMs,
            })

            expect(lazyLoader['refreshAgeMs']).toBe(refreshAgeMs)
            expect(lazyLoader['refreshNullAgeMs']).toBe(refreshAgeMs)
            expect(lazyLoader['refreshBackgroundAgeMs']).toBe(undefined)
            expect(lazyLoader['refreshJitterMs']).toBe(refreshAgeMs / 5)
        })
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
            const result2 = await lazyLoader.get('key1')
            expect(result2).toBeNull()
            expect(loader).toHaveBeenCalledTimes(1)
        })

        it('handles undefined values', async () => {
            loader.mockResolvedValue({ key1: undefined })

            const result = await lazyLoader.get('key1')
            expect(result).toBeNull()
            const result2 = await lazyLoader.get('key1')
            expect(result2).toBeNull()
            expect(loader).toHaveBeenCalledTimes(1)
        })

        it('can add additional keys to the cache', async () => {
            loader.mockResolvedValue({ key1: 'value1', key2: 'value2' })
            const result = await lazyLoader.get('key1')
            expect(result).toBe('value1')
            expect(lazyLoader.getCache()).toEqual({ key1: 'value1', key2: 'value2' })
            const result2 = await lazyLoader.get('key2')
            expect(result2).toBe('value2')
            expect(loader).toHaveBeenCalledTimes(1)
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
            jest.spyOn(Date, 'now').mockReturnValue(start + 1000 * 60 * 6)

            await lazyLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(2)
        })

        it('respects custom refreshAge', async () => {
            const customLoader = new LazyLoader({
                name: 'test',
                loader,
                refreshAgeMs: 1000 * 60 * 2, // 2 minutes
            })

            loader.mockResolvedValueOnce({ key1: 'value1' }).mockResolvedValueOnce({ key1: 'value2' })

            await customLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(1)

            // Fast forward past custom refresh age
            jest.spyOn(Date, 'now').mockReturnValue(start + 1000 * 60 * 3) // 3 minutes

            await customLoader.get('key1')
            expect(loader).toHaveBeenCalledTimes(2)
        })
    })

    describe('error handling', () => {
        it('throws errors by default', async () => {
            loader.mockRejectedValue(new Error('Test error'))

            await expect(lazyLoader.get('key1')).rejects.toThrow('Test error')
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

    describe('parallel loading', () => {
        it('should bundle loads for the same key', async () => {
            loader.mockResolvedValue({ key1: { foo: 'bar' } })

            const results = await Promise.all([lazyLoader.get('key1'), lazyLoader.get('key1'), lazyLoader.get('key2')])

            expect(results).toEqual([{ foo: 'bar' }, { foo: 'bar' }, null])
            expect(results[0]).toBe(results[1])
            expect(loader).toHaveBeenCalledTimes(1)
            expect(loader).toHaveBeenCalledWith(['key1', 'key2'])
        })

        it('should load multiple values in parallel', async () => {
            loader.mockImplementation(async (keys) => {
                await new Promise((resolve) => setTimeout(resolve, 100))
                return keys.reduce(
                    (acc: any, key: string) => {
                        acc[key] = { val: key }
                        return acc
                    },
                    {} as Record<string, any>
                )
            })

            const result1 = lazyLoader.get('key1')
            // Should join first request
            const result2 = lazyLoader.get('key2')
            await delay(50)
            // Should load key2 and join second request
            const result3 = lazyLoader.get('key3')
            const result4 = lazyLoader.getMany(['key1', 'key2', 'key3'])

            const results = await Promise.all([result1, result2, result3, result4])

            expect(results).toMatchInlineSnapshot(`
                [
                  {
                    "val": "key1",
                  },
                  {
                    "val": "key2",
                  },
                  {
                    "val": "key3",
                  },
                  {
                    "key1": {
                      "val": "key1",
                    },
                    "key2": {
                      "val": "key2",
                    },
                    "key3": {
                      "val": "key3",
                    },
                  },
                ]
            `)
            expect(loader).toHaveBeenCalledTimes(2)
            expect(loader).toHaveBeenNthCalledWith(1, ['key1', 'key2'])
            expect(loader).toHaveBeenNthCalledWith(2, ['key3'])
        })
    })

    describe('background refreshing', () => {
        let loadSpy: jest.SpyInstance

        beforeEach(() => {
            lazyLoader = new LazyLoader({
                name: 'test',
                loader,
                refreshAgeMs: 1000 * 60 * 2, // 2 minutes
                refreshBackgroundAgeMs: 1000 * 60 * 1, // 1 minute
                refreshJitterMs: 0, // Simplify the tests
            })

            loadSpy = jest.spyOn(lazyLoader as any, 'load')
        })

        it('should refresh in the background if between ages', async () => {
            let count = 0
            loader.mockImplementation(() => {
                count++
                return { key1: 'value' + count }
            })

            const result = await lazyLoader.get('key1')
            expect(loadSpy).toHaveBeenCalledTimes(1)
            expect(loader).toHaveBeenCalledTimes(1)
            expect(result).toBe('value1')
            loadSpy.mockClear()
            loader.mockClear()

            // Fast forward past refresh background age
            jest.spyOn(Date, 'now').mockReturnValue(start + 1000 * 60 * 1.5)
            const result2 = await lazyLoader.get('key1')
            expect(result2).toBe('value1') // Value should immediately be returned
            expect(loadSpy).toHaveBeenCalledTimes(1) // Load was called
            expect(loader).toHaveBeenCalledTimes(0) // But it didnt block
            loadSpy.mockClear()
            loader.mockClear()

            // Check in flight cache
            const result3 = await lazyLoader.get('key1')
            expect(result3).toBe('value1')
            expect(loadSpy).toHaveBeenCalledTimes(1)
            expect(loader).toHaveBeenCalledTimes(0)
            loadSpy.mockClear()
            loader.mockClear()
            // Let the background refresh complete
            await delay(100)
            const result4 = await lazyLoader.get('key1')
            expect(result4).toBe('value2')
            expect(loadSpy).toHaveBeenCalledTimes(0)
            expect(loader).toHaveBeenCalledTimes(1)
        })
    })

    describe('LRU eviction with maxSize', () => {
        it('should evict least recently used entries when maxSize is exceeded', async () => {
            const customLoader = new LazyLoader({
                name: 'test',
                loader,
                maxSize: 3,
                refreshJitterMs: 0,
            })

            // Add 3 entries
            loader.mockResolvedValueOnce({ key1: 'value1', key2: 'value2', key3: 'value3' })
            await customLoader.getMany(['key1', 'key2', 'key3'])
            expect(Object.keys(customLoader.getCache()).length).toBe(3)

            // Access key1 and key2 to update their lastUsed times
            jest.spyOn(Date, 'now').mockReturnValue(start + 1000)
            await customLoader.get('key1')
            jest.spyOn(Date, 'now').mockReturnValue(start + 2000)
            await customLoader.get('key2')

            // Add a 4th entry - should evict key3 (least recently used)
            jest.spyOn(Date, 'now').mockReturnValue(start + 3000)
            loader.mockResolvedValueOnce({ key4: 'value4' })
            await customLoader.get('key4')

            const cache = customLoader.getCache()
            expect(Object.keys(cache).length).toBe(3)
            expect(cache).toEqual({ key1: 'value1', key2: 'value2', key4: 'value4' })
        })

        it('should handle bulk additions that exceed maxSize', async () => {
            const customLoader = new LazyLoader({
                name: 'test',
                loader,
                maxSize: 2,
                refreshJitterMs: 0,
            })

            // Add 5 entries at once - should keep only 2
            loader.mockResolvedValueOnce({
                key1: 'value1',
                key2: 'value2',
                key3: 'value3',
                key4: 'value4',
                key5: 'value5',
            })

            await customLoader.getMany(['key1', 'key2', 'key3', 'key4', 'key5'])

            const cache = customLoader.getCache()
            expect(Object.keys(cache).length).toBe(2)
            // When all have the same lastUsed time, eviction order depends on iteration order
            // Just verify we have exactly 2 entries
        })
    })
})
