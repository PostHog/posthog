import { quotaCores } from './cores.ts'

describe('quotaCores', () => {
    const reader =
        (files: Record<string, string>) =>
        (path: string): string => {
            const body = files[path]
            if (body === undefined) {
                throw new Error(`ENOENT: ${path}`)
            }
            return body
        }

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
