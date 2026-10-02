import os from 'node:os'

import { threadpoolConcurrency } from './threadpool-concurrency'

describe('threadpoolConcurrency', () => {
    const uvThreadpoolSize = process.env.UV_THREADPOOL_SIZE

    afterEach(() => {
        jest.restoreAllMocks()
        if (uvThreadpoolSize === undefined) {
            delete process.env.UV_THREADPOOL_SIZE
        } else {
            process.env.UV_THREADPOOL_SIZE = uvThreadpoolSize
        }
    })

    it.each([
        ['resolves to available CPUs when below the pool', 3, '4', 3],
        ['is capped by the threadpool size', 16, '4', 4],
        ['never resolves below 1', 0, '0', 1],
        ['falls back to four when the pool size is unset', 16, undefined, 4],
    ])('%s', (_name, cpus, poolSize, expected) => {
        jest.spyOn(os, 'availableParallelism').mockReturnValue(cpus)
        if (poolSize === undefined) {
            delete process.env.UV_THREADPOOL_SIZE
        } else {
            process.env.UV_THREADPOOL_SIZE = poolSize
        }

        expect(threadpoolConcurrency()).toBe(expected)
    })
})
