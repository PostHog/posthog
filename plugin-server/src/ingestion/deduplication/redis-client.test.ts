import { PluginsServerConfig } from '../../types'
import { createDeduplicationRedis, DeduplicationOptions, DeduplicationRedis } from './redis-client'

const getConfig = (): PluginsServerConfig =>
    ({
        REDIS_URL: process.env.REDIS_URL || 'redis://localhost:6379',
        DEDUPLICATION_REDIS_HOST: process.env.DEDUPLICATION_REDIS_HOST || '',
        DEDUPLICATION_REDIS_PORT: parseInt(process.env.DEDUPLICATION_REDIS_PORT || '6379'),
        DEDUPLICATION_TTL_SECONDS: 60,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 20,
        DEDUPLICATION_REDIS_PREFIX: 'test',
    } as PluginsServerConfig)

// Helper function to pre-populate keys in Redis
const insertKeys = async (deduplicationRedis: DeduplicationRedis, keys: string[], ttl: number): Promise<void> => {
    await deduplicationRedis.withClient(async (client) => {
        for (const key of keys) {
            await client.set(key, '1', 'EX', ttl)
        }
    })
}

describe('DeduplicationRedis Integration Tests', () => {
    it.concurrent('should handle invalid Redis config gracefully without throwing', async () => {
        const invalidConfig: PluginsServerConfig = {
            ...getConfig(),
            REDIS_URL: 'redis://invalid-host:9999',
            DEDUPLICATION_REDIS_HOST: 'invalid-host',
            DEDUPLICATION_REDIS_PORT: 9999,
        }

        const deduplicationRedis = new DeduplicationRedis(invalidConfig)

        try {
            // Should not throw during deduplicate call
            const result = await deduplicationRedis.deduplicate({
                keys: ['test:key:1', 'test:key:2', 'test:key:3'],
                ttl: 60,
            })

            // Should return safe defaults
            expect(result.processed).toBe(3)
            expect(result.duplicates).toBe(0)

            // Should also work for deduplicateIds
            const idsResult = await deduplicationRedis.deduplicateIds({
                keys: ['test:id:1', 'test:id:2'],
                ttl: 60,
            })

            expect(idsResult.processed).toBe(2)
            expect(idsResult.duplicates).toEqual(new Set())
        } finally {
            await deduplicationRedis.destroy()
        }
    })

    it.concurrent('should initialize automatically on first use', async () => {
        const redis = new DeduplicationRedis(getConfig())
        await redis.destroy()
    })

    it.concurrent('should identify new keys as non-duplicates', async () => {
        const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
        const deduplicationRedis = new DeduplicationRedis(getConfig())

        try {
            const options: DeduplicationOptions = {
                keys: [`${testId}:new:1`, `${testId}:new:2`, `${testId}:new:3`],
                ttl: 60,
            }

            const result = await deduplicationRedis.deduplicate(options)

            expect(result.processed).toBe(3)
            expect(result.duplicates).toBe(0)
        } finally {
            await deduplicationRedis.destroy()
        }
    })

    it.concurrent(
        'should identify existing keys as duplicates',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const options: DeduplicationOptions = {
                    keys: [`${testId}:existing:1`, `${testId}:existing:2`],
                    ttl: 60,
                }

                // First call - should be all new
                const firstResult = await deduplicationRedis.deduplicate(options)
                expect(firstResult.processed).toBe(2)
                expect(firstResult.duplicates).toBe(0)

                // Second call - should be all duplicates
                const secondResult = await deduplicationRedis.deduplicate(options)
                expect(secondResult.processed).toBe(2)
                expect(secondResult.duplicates).toBe(2)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle mixed new and existing keys',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                // Set up some existing keys
                const existingKeys = [`${testId}:mixed:1`, `${testId}:mixed:2`]
                await insertKeys(deduplicationRedis, deduplicationRedis.prefixKeys(existingKeys), 60)

                const testOptions: DeduplicationOptions = {
                    keys: [`${testId}:mixed:1`, `${testId}:mixed:3`],
                    ttl: 60,
                }

                // Test with mixed keys
                const result = await deduplicationRedis.deduplicate(testOptions)
                expect(result.processed).toBe(2)
                expect(result.duplicates).toBe(1) // mixed:1 exists
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle empty keys array',
        async () => {
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const options: DeduplicationOptions = {
                    keys: [],
                    ttl: 60,
                }

                const result = await deduplicationRedis.deduplicate(options)
                expect(result.processed).toBe(0)
                expect(result.duplicates).toBe(0)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should respect TTL expiration',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const options: DeduplicationOptions = {
                    keys: [`${testId}:ttl:1`],
                    ttl: 1, // 1 second TTL
                }

                // First call
                const firstResult = await deduplicationRedis.deduplicate(options)
                expect(firstResult.duplicates).toBe(0)

                // Wait for TTL to expire
                await new Promise((resolve) => setTimeout(resolve, 1100))

                // Second call after TTL expiration
                const secondResult = await deduplicationRedis.deduplicate(options)
                expect(secondResult.duplicates).toBe(0)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle large number of keys',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const keys = Array.from({ length: 1000 }, (_, i) => `${testId}:large:${i}`)
                const options: DeduplicationOptions = {
                    keys,
                    ttl: 60,
                }

                const result = await deduplicationRedis.deduplicate(options)
                expect(result.processed).toBe(1000)
                expect(result.duplicates).toBe(0)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should provide working Redis client',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const result = await deduplicationRedis.withClient(async (client) => {
                    await client.set(`${testId}:withclient:1`, 'value')
                    const value = await client.get(`${testId}:withclient:1`)
                    return value
                })

                expect(result).toBe('value')
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle client operations that throw errors',
        async () => {
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                await expect(
                    deduplicationRedis.withClient(async (client) => {
                        await client.evalsha('invalid-sha', 0)
                    })
                ).rejects.toThrow()
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should work with deduplicateKeys convenience method',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const keys = [`${testId}:convenience:1`, `${testId}:convenience:2`]
                const duplicates = await deduplicationRedis.deduplicateKeys(keys, 60)
                expect(duplicates).toBe(0) // Should be no duplicates
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle concurrent deduplication requests',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const promises = Array.from({ length: 10 }, (_, i) => {
                    const options: DeduplicationOptions = {
                        keys: [`${testId}:concurrent:${i}:1`, `${testId}:concurrent:${i}:2`],
                        ttl: 60,
                    }
                    return deduplicationRedis.deduplicate(options)
                })

                const results = await Promise.all(promises)

                results.forEach((result) => {
                    expect(result.processed).toBe(2)
                    expect(result.duplicates).toBe(0)
                })
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle concurrent access to same keys',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const keys = [`${testId}:concurrent:same:1`, `${testId}:concurrent:same:2`]
                const options: DeduplicationOptions = { keys, ttl: 60 }

                const promises = Array.from({ length: 5 }, () => deduplicationRedis.deduplicate(options))

                const results = await Promise.all(promises)

                // One should have 0 duplicates, others should have 2
                const duplicateCounts = results.map((r) => r.duplicates)
                expect(duplicateCounts).toContain(0)
                expect(duplicateCounts.filter((count) => count === 2).length).toBe(4)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should create working DeduplicationRedis instance',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const instance = createDeduplicationRedis(getConfig())

            try {
                const result = await instance.deduplicate({
                    keys: [`${testId}:factory:1`],
                    ttl: 60,
                })

                expect(result.processed).toBe(1)
                expect(result.duplicates).toBe(0)
            } finally {
                await instance.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should only consider duplicates within ttl',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const options: DeduplicationOptions = {
                    keys: [`${testId}:ttl:1`],
                    ttl: 1, // 1 second TTL
                }

                // First call - should be new
                const firstResult = await deduplicationRedis.deduplicate(options)
                expect(firstResult.duplicates).toBe(0)

                // Second call - should be duplicate
                const secondResult = await deduplicationRedis.deduplicate(options)
                expect(secondResult.duplicates).toBe(1)

                // Wait 2 second for TTL to expire
                await new Promise((resolve) => setTimeout(resolve, 2000))

                // Third call after TTL expiration - should be new again
                const thirdResult = await deduplicationRedis.deduplicate(options)
                expect(thirdResult.duplicates).toBe(0)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    // it.concurrent(
    //     'should reset TTL when duplicate is found with deduplicate method',
    //     async () => {
    //         const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
    //         const deduplicationRedis = new DeduplicationRedis(getConfig())

    //         try {
    //             const keys = [`${testId}:ttl:reset:1`]
    //             const options: DeduplicationOptions = { keys, ttl: 10 }

    //             // First call - set key with 10 second TTL
    //             const firstResult = await deduplicationRedis.deduplicate(options)
    //             expect(firstResult.duplicates).toBe(0)

    //             // Check initial TTL
    //             const initialTtl = await deduplicationRedis.withClient(async (client) => {
    //                 return await client.ttl(deduplicationRedis.prefixKeys(keys)[0])
    //             })
    //             expect(initialTtl).toBeGreaterThan(0)
    //             expect(initialTtl).toBeLessThanOrEqual(10)

    //             // Wait a bit to let TTL decrease
    //             await new Promise(resolve => setTimeout(resolve, 2000))

    //             // Check TTL after waiting
    //             const ttlAfterWait = await deduplicationRedis.withClient(async (client) => {
    //                 return await client.ttl(deduplicationRedis.prefixKeys(keys)[0])
    //             })
    //             expect(ttlAfterWait).toBeLessThan(initialTtl)

    //             // Second call - should be duplicate and reset TTL
    //             const secondResult = await deduplicationRedis.deduplicate(options)
    //             expect(secondResult.duplicates).toBe(1)

    //             // Check TTL after duplicate - should be reset to full TTL
    //             const ttlAfterDuplicate = await deduplicationRedis.withClient(async (client) => {
    //                 return await client.ttl(deduplicationRedis.prefixKeys(keys)[0])
    //             })
    //             expect(ttlAfterDuplicate).toBeGreaterThan(ttlAfterWait)
    //             expect(ttlAfterDuplicate).toBeLessThanOrEqual(10)
    //         } finally {
    //             await deduplicationRedis.destroy()
    //         }
    //     },
    //     10000
    // )

    it.concurrent(
        'should provide health check via ping',
        async () => {
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const pong = await deduplicationRedis.ping()
                expect(pong).toBe('PONG')
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should handle all test scenarios concurrently',
        async () => {
            const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                const promises = [
                    // Basic deduplication
                    deduplicationRedis.deduplicate({
                        keys: [`${testId}:conc:basic:1`, `${testId}:conc:basic:2`],
                        ttl: 60,
                    }),
                    // Empty keys
                    deduplicationRedis.deduplicate({
                        keys: [],
                        ttl: 60,
                    }),
                    // Large keys
                    deduplicationRedis.deduplicate({
                        keys: Array.from({ length: 100 }, (_, i) => `${testId}:conc:large:${i}`),
                        ttl: 60,
                    }),
                    // WithClient operations
                    deduplicationRedis.withClient(async (client) => {
                        await client.set(`${testId}:conc:withclient:1`, 'value')
                        const value = await client.get(`${testId}:conc:withclient:1`)
                        return value
                    }),
                    // Deduplicate via convenience method
                    deduplicationRedis.deduplicateKeys([`${testId}:conc:direct:1`], 60),
                ]

                const results = await Promise.all(promises)

                // Verify results
                expect(results[0]).toEqual({ duplicates: 0, processed: 2 })
                expect(results[1]).toEqual({ duplicates: 0, processed: 0 })
                expect(results[2]).toEqual({ duplicates: 0, processed: 100 })
                expect(results[3]).toBe('value')
                expect(results[4]).toBe(0)
            } finally {
                await deduplicationRedis.destroy()
            }
        },
        5000
    )

    it.concurrent(
        'should throw error when used after destruction',
        async () => {
            const deduplicationRedis = new DeduplicationRedis(getConfig())

            try {
                await deduplicationRedis.destroy()

                await expect(deduplicationRedis.deduplicate({ keys: ['test'], ttl: 60 })).rejects.toThrow(
                    'DeduplicationRedis has been destroyed'
                )
            } finally {
                // Already destroyed
            }
        },
        5000
    )

    describe('DeduplicateIds Method Tests', () => {
        it.concurrent(
            'should return empty array for new keys with deduplicateIds',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const options: DeduplicationOptions = {
                        keys: [`${testId}:ids:new:1`, `${testId}:ids:new:2`, `${testId}:ids:new:3`],
                        ttl: 60,
                    }

                    const result = await deduplicationRedis.deduplicateIds(options)

                    expect(result.processed).toBe(3)
                    expect(result.duplicates).toEqual(new Set())
                    expect(result.duplicates.size).toBe(0)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            5000
        )

        it.concurrent(
            'should return actual duplicate IDs with deduplicateIds',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = [`${testId}:ids:existing:1`, `${testId}:ids:existing:2`]
                    const options: DeduplicationOptions = { keys, ttl: 60 }

                    // First call - should be all new
                    const firstResult = await deduplicationRedis.deduplicateIds(options)
                    expect(firstResult.processed).toBe(2)
                    expect(firstResult.duplicates).toEqual(new Set())

                    // Second call - should return the duplicate IDs
                    const secondResult = await deduplicationRedis.deduplicateIds(options)
                    expect(secondResult.processed).toBe(2)
                    expect(secondResult.duplicates).toEqual(new Set(deduplicationRedis.prefixKeys(keys)))
                    expect(secondResult.duplicates.size).toBe(2)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            5000
        )

        it.concurrent(
            'should return only duplicate IDs for mixed keys with deduplicateIds',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const existingKeys = [`${testId}:ids:mixed:1`, `${testId}:ids:mixed:2`]
                    const mixedKeys = [`${testId}:ids:mixed:1`, `${testId}:ids:mixed:3`]

                    // Set up existing keys
                    const prefixedKeys = deduplicationRedis.prefixKeys(existingKeys)
                    await insertKeys(deduplicationRedis, prefixedKeys, 60)

                    // Test with mixed keys
                    const result = await deduplicationRedis.deduplicateIds({ keys: mixedKeys, ttl: 60 })
                    expect(result.processed).toBe(2)
                    expect(result.duplicates).toEqual(new Set(deduplicationRedis.prefixKeys([`${testId}:ids:mixed:1`])))
                    expect(result.duplicates.size).toBe(1)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            5000
        )

        it.concurrent(
            'should handle empty keys array with deduplicateIds',
            async () => {
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const result = await deduplicationRedis.deduplicateIds({ keys: [], ttl: 60 })
                    expect(result.processed).toBe(0)
                    expect(result.duplicates).toEqual(new Set())
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            5000
        )

        it.concurrent(
            'should respect TTL expiration with deduplicateIds',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = [`${testId}:ids:ttl:1`]
                    const options: DeduplicationOptions = { keys, ttl: 2 }
                    const prefixedKeys = deduplicationRedis.prefixKeys(keys)

                    // First call - should be new
                    const firstResult = await deduplicationRedis.deduplicateIds(options)
                    expect(firstResult.duplicates).toEqual(new Set())

                    // Second call - should be duplicate
                    const secondResult = await deduplicationRedis.deduplicateIds(options)
                    expect(secondResult.duplicates).toEqual(new Set(prefixedKeys))

                    // Wait for TTL to expire with buffer time
                    await new Promise((resolve) => setTimeout(resolve, 2500))

                    // Third call after TTL expiration - should be new again
                    const thirdResult = await deduplicationRedis.deduplicateIds(options)
                    expect(thirdResult.duplicates).toEqual(new Set())
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            8000
        )

        // it.concurrent(
        //     'should reset TTL when duplicate is found with deduplicateIds method',
        //     async () => {
        //         const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
        //         const deduplicationRedis = new DeduplicationRedis(getConfig())

        //         try {
        //             const keys = [`${testId}:ttl:reset:ids:1`]
        //             const options: DeduplicationOptions = { keys, ttl: 10 }

        //             // First call - set key with 10 second TTL
        //             const firstResult = await deduplicationRedis.deduplicateIds(options)
        //             expect(firstResult.duplicates).toEqual([])

        //             // Check initial TTL
        //             const initialTtl = await deduplicationRedis.withClient(async (client) => {
        //                 return await client.ttl(deduplicationRedis.prefixKeys(keys)[0])
        //             })
        //             expect(initialTtl).toBeGreaterThan(0)
        //             expect(initialTtl).toBeLessThanOrEqual(10)

        //             // Wait a bit to let TTL decrease
        //             await new Promise(resolve => setTimeout(resolve, 2000))

        //             // Check TTL after waiting
        //             const ttlAfterWait = await deduplicationRedis.withClient(async (client) => {
        //                 return await client.ttl(deduplicationRedis.prefixKeys(keys)[0])
        //             })
        //             expect(ttlAfterWait).toBeLessThan(initialTtl)

        //             // Second call - should be duplicate and reset TTL
        //             const secondResult = await deduplicationRedis.deduplicateIds(options)
        //             expect(secondResult.duplicates).toEqual(deduplicationRedis.prefixKeys(keys))

        //             // Check TTL after duplicate - should be reset to full TTL
        //             const ttlAfterDuplicate = await deduplicationRedis.withClient(async (client) => {
        //                 return await client.ttl(deduplicationRedis.prefixKeys(keys)[0])
        //             })
        //             expect(ttlAfterDuplicate).toBeGreaterThan(ttlAfterWait)
        //             expect(ttlAfterDuplicate).toBeLessThanOrEqual(10)
        //         } finally {
        //             await deduplicationRedis.destroy()
        //         }
        //     },
        //     10000
        // )
    })

    describe('High Volume Tests - 500 Keys', () => {
        it.concurrent(
            'should handle 500 new keys with deduplicate method',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = Array.from({ length: 500 }, (_, i) => `${testId}:volume:new:${i}`)
                    const options: DeduplicationOptions = { keys, ttl: 60 }

                    const result = await deduplicationRedis.deduplicate(options)
                    expect(result.processed).toBe(500)
                    expect(result.duplicates).toBe(0)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            10000
        )

        it.concurrent(
            'should handle 500 duplicate keys with deduplicate method',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = Array.from({ length: 500 }, (_, i) => `${testId}:volume:dup:${i}`)
                    const options: DeduplicationOptions = { keys, ttl: 60 }

                    // First call - set up the keys
                    const firstResult = await deduplicationRedis.deduplicate(options)
                    expect(firstResult.processed).toBe(500)
                    expect(firstResult.duplicates).toBe(0)

                    // Second call - should find all 500 as duplicates
                    const secondResult = await deduplicationRedis.deduplicate(options)
                    expect(secondResult.processed).toBe(500)
                    expect(secondResult.duplicates).toBe(500)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            10000
        )

        it.concurrent(
            'should handle 500 new keys with deduplicateIds method',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = Array.from({ length: 500 }, (_, i) => `${testId}:ids:volume:new:${i}`)
                    const options: DeduplicationOptions = { keys, ttl: 60 }

                    const result = await deduplicationRedis.deduplicateIds(options)
                    expect(result.processed).toBe(500)
                    expect(result.duplicates).toEqual(new Set())
                    expect(result.duplicates.size).toBe(0)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            10000
        )

        it.concurrent(
            'should return 500 duplicate IDs with deduplicateIds method',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = Array.from({ length: 500 }, (_, i) => `${testId}:ids:volume:dup:${i}`)
                    const prefixedKeys = deduplicationRedis.prefixKeys(keys)
                    const options: DeduplicationOptions = { keys, ttl: 60 }

                    // First call - set up the keys
                    const firstResult = await deduplicationRedis.deduplicateIds(options)
                    expect(firstResult.processed).toBe(500)
                    expect(firstResult.duplicates).toEqual(new Set())

                    // Second call - should return all 500 keys as duplicates
                    const secondResult = await deduplicationRedis.deduplicateIds(options)
                    expect(secondResult.processed).toBe(500)
                    expect(secondResult.duplicates).toEqual(new Set(prefixedKeys))
                    expect(secondResult.duplicates.size).toBe(500)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            10000
        )

        it.concurrent(
            'should handle mixed scenario with 250 new and 250 duplicate keys using deduplicate method',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    // Set up 250 keys first using helper method
                    const existingKeys = Array.from({ length: 250 }, (_, i) => `${testId}:mixed:dedupe:${i}`)
                    await insertKeys(deduplicationRedis, deduplicationRedis.prefixKeys(existingKeys), 60)

                    // Test with 250 existing + 250 new keys
                    const newKeys = Array.from({ length: 250 }, (_, i) => `${testId}:new:dedupe:${i}`)
                    const mixedKeys = [...existingKeys, ...newKeys]

                    // Test with deduplicate method
                    const countResult = await deduplicationRedis.deduplicate({ keys: mixedKeys, ttl: 60 })
                    expect(countResult.processed).toBe(500)
                    expect(countResult.duplicates).toBe(250)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            10000
        )

        it.concurrent(
            'should handle mixed scenario with 250 new and 250 duplicate keys using deduplicateIds method',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    // Set up 250 keys first using helper method
                    const existingKeys = Array.from({ length: 250 }, (_, i) => `${testId}:mixed:ids:${i}`)
                    const prefixedKeys = deduplicationRedis.prefixKeys(existingKeys)
                    await insertKeys(deduplicationRedis, prefixedKeys, 60)

                    // Test with 250 existing + 250 new keys
                    const newKeys = Array.from({ length: 250 }, (_, i) => `${testId}:new:ids:${i}`)
                    const mixedKeys = [...existingKeys, ...newKeys]

                    // Test with deduplicateIds method
                    const idsResult = await deduplicationRedis.deduplicateIds({ keys: mixedKeys, ttl: 60 })
                    expect(idsResult.processed).toBe(500)
                    expect(idsResult.duplicates).toEqual(new Set(prefixedKeys))
                    expect(idsResult.duplicates.size).toBe(250)
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            10000
        )
    })

    describe('Performance and Stress Tests', () => {
        it.concurrent(
            'should handle concurrent requests with 500 keys each',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const promises = Array.from({ length: 5 }, (_, batchIndex) => {
                        const keys = Array.from(
                            { length: 500 },
                            (_, i) => `${testId}:concurrent:batch${batchIndex}:${i}`
                        )
                        return deduplicationRedis.deduplicate({ keys, ttl: 60 })
                    })

                    const results = await Promise.all(promises)

                    results.forEach((result) => {
                        expect(result.processed).toBe(500)
                        expect(result.duplicates).toBe(0)
                    })
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            15000
        )

        it.concurrent(
            'should maintain consistency between deduplicate and deduplicateIds methods',
            async () => {
                const testId = `test:${Date.now()}:${Math.random().toString(36).substring(2, 9)}`
                const deduplicationRedis = new DeduplicationRedis(getConfig())

                try {
                    const keys = Array.from({ length: 100 }, (_, i) => `${testId}:consistency:${i}`)
                    const options: DeduplicationOptions = { keys, ttl: 60 }
                    const prefixedKeys = deduplicationRedis.prefixKeys(keys)

                    // Set up keys using helper method
                    await insertKeys(deduplicationRedis, prefixedKeys, 60)

                    // Test consistency between both methods
                    const [countResult, idsResult] = await Promise.all([
                        deduplicationRedis.deduplicate(options),
                        deduplicationRedis.deduplicateIds(options),
                    ])

                    expect(countResult.processed).toBe(idsResult.processed)
                    expect(countResult.duplicates).toBe(idsResult.duplicates.size)
                    expect(idsResult.duplicates).toEqual(new Set(prefixedKeys))
                } finally {
                    await deduplicationRedis.destroy()
                }
            },
            5000
        )
    })
})
