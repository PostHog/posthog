import { resolveMlAnonymizeMaxConcurrency } from './config'

describe('resolveMlAnonymizeMaxConcurrency', () => {
    it.each([
        ['explicit value passes through verbatim, even above the pool', 8, 3, 4, 8],
        ['sentinel resolves to available CPUs when below the pool', 0, 3, 4, 3],
        ['sentinel is capped by the threadpool size', 0, 16, 4, 4],
        ['sentinel never resolves below 1', -1, 0, 0, 1],
    ])('%s', (_name, configured, cpus, poolSize, expected) => {
        expect(resolveMlAnonymizeMaxConcurrency(configured, cpus, poolSize)).toBe(expected)
    })
})
