import { totalmem } from 'node:os'

import { memoryLimitBytes, quotaCores, workersForMemoryLimit } from './cores.ts'

const reader =
    (files: Record<string, string>) =>
    (path: string): string => {
        const body = files[path]
        if (body === undefined) {
            throw new Error(`ENOENT: ${path}`)
        }
        return body
    }

describe('quotaCores', () => {
    const V2 = '/sys/fs/cgroup/cpu.max'
    const V1_QUOTA = '/sys/fs/cgroup/cpu/cpu.cfs_quota_us'
    const V1_PERIOD = '/sys/fs/cgroup/cpu/cpu.cfs_period_us'

    it.each([
        ['cgroup v2, whole cores', { [V2]: '400000 100000\n' }, 4],
        ['cgroup v2, fractional floors rather than rounds up', { [V2]: '3500 1000\n' }, 3],
        ['cgroup v2, sub-core still yields one', { [V2]: '50000 100000\n' }, 1],
        ['cgroup v1 when v2 is absent', { [V1_QUOTA]: '200000\n', [V1_PERIOD]: '100000\n' }, 2],
    ])('reads %s', (_case, files, expected) => {
        expect(quotaCores(reader(files))).toBe(expected)
    })

    it.each([
        ['uncapped v2 reports max', { [V2]: 'max 100000\n' }],
        ['uncapped v1 reports a negative quota', { [V1_QUOTA]: '-1\n', [V1_PERIOD]: '100000\n' }],
        ['no cgroup files at all', {}],
        ['a malformed single token', { [V2]: 'garbage\n' }],
    ])('returns null when %s', (_case, files) => {
        // null is what makes the caller fall back to a small constant. Returning a number here, or
        // letting the host's core count through, is how a capped pod ends up oversubscribed.
        expect(quotaCores(reader(files))).toBeNull()
    })
})

describe('memoryLimitBytes', () => {
    const V2 = '/sys/fs/cgroup/memory.max'
    const V1 = '/sys/fs/cgroup/memory/memory.limit_in_bytes'

    it('reads the v2 limit, and the v1 one when v2 is absent', () => {
        expect(memoryLimitBytes(reader({ [V2]: '2147483648\n' }))).toBe(2147483648)
        expect(memoryLimitBytes(reader({ [V1]: '2147483648\n' }))).toBe(2147483648)
    })

    it.each([
        ['uncapped v2 reports max', { [V2]: 'max\n' }],
        // cgroup v1 has no word for uncapped and reports a number near 2^63 instead. Taken at face
        // value it divides into a worker count far past any real pod, which is the wrong direction to
        // be wrong in: the cap exists to stop a many-core node OOM-killing the sidecar at startup.
        ['uncapped v1 reports a sentinel near 2^63', { [V1]: '9223372036854771712\n' }],
        ['no cgroup files at all', {}],
        ['a malformed value', { [V2]: 'garbage\n' }],
    ])('returns null when %s', (_case, files) => {
        expect(memoryLimitBytes(reader(files))).toBeNull()
    })

    it('ignores a limit at or above the host, which is what an uncapped container reads', () => {
        expect(memoryLimitBytes(reader({ [V2]: `${totalmem()}\n` }))).toBeNull()
    })
})

describe('memoryBoundedWorkers', () => {
    // The reserve stops the arithmetic handing every byte of the limit to workers, leaving the main
    // thread and the overlap during a replacement unbudgeted. Note what this says about the deployed
    // 4-core/2Gi shape: memory, not cores, is the binding constraint there, and a pod has to carry
    // roughly 4Gi before four workers fit. Sizing by cores alone would have put four workers in 2Gi,
    // which measurement says needs about 3.1Gi at peak.
    it.each([
        ['2Gi', 2 * 1024 ** 3, 3],
        ['3Gi', 3 * 1024 ** 3, 5],
        ['4Gi', 4 * 1024 ** 3, 7],
        ['1Gi, below one worker plus the reserve', 1024 ** 3, 1],
        ['256Mi, below even the reserve', 256 * 1024 ** 2, 1],
    ])('allows %s to hold %s workers', (_case, limit, expected) => {
        expect(workersForMemoryLimit(limit)).toBe(expected)
    })
})
