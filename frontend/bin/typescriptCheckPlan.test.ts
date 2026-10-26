import { tsgoPlan } from './typescriptCheckPlan.mjs'

const GIB = 1024 ** 3

describe('tsgoPlan', () => {
    it.each([
        ['unknown headroom', null, { mode: 'full' }],
        ['24 GiB of headroom', 24 * GIB, { mode: 'full' }],
        ['20 GiB of headroom', 20 * GIB, { mode: 'constrained', goMemLimit: '10GiB', headroomGib: '20.0' }],
        ['12 GiB of headroom', 12 * GIB, { mode: 'constrained', goMemLimit: '6GiB', headroomGib: '12.0' }],
        ['11 GiB of headroom', 11 * GIB, { mode: 'refuse', message: expect.stringContaining('Only 11.0 GiB') }],
        ['negative headroom', -1 * GIB, { mode: 'refuse', message: expect.stringContaining('Only 0.0 GiB') }],
    ])('with %s', (_, headroom, expected) => {
        expect(tsgoPlan(headroom)).toEqual(expected)
    })
})
