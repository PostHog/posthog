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
                refreshAge: 1000 * 60 * 2, // 2 minutes
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
})
