const GIB = 1024 ** 3
const UNTUNED_MIN_HEADROOM_GIB = 24
const MIN_GOMEMLIMIT_GIB = 6
const HEADROOM_AT_MIN_GOMEMLIMIT_GIB = 9

export function tsgoPlan(headroom) {
    if (headroom === null || headroom >= UNTUNED_MIN_HEADROOM_GIB * GIB) {
        return { mode: 'full' }
    }
    const headroomGib = (Math.max(0, headroom) / GIB).toFixed(1)
    if (headroom < HEADROOM_AT_MIN_GOMEMLIMIT_GIB * GIB) {
        return {
            mode: 'refuse',
            message: `Only ${headroomGib} GiB of memory headroom is free, and the TypeScript check needs ${HEADROOM_AT_MIN_GOMEMLIMIT_GIB} GiB. Stop background processes such as a Storybook or app dev server, then run this check again.`,
        }
    }
    const goMemLimit = `${Math.max(MIN_GOMEMLIMIT_GIB, Math.floor(headroom / GIB / 2))}GiB`
    return { mode: 'constrained', goMemLimit, headroomGib }
}
