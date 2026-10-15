// src/index.tsx imports this module, so it ships on the entry chunk of every page. Keep it free of imports.

export type BootMilestone =
    | 'entry-start'
    | 'app-modules-loaded'
    | 'render-start'
    | 'app-booted'
    | 'first-scene-rendered'

const MARK_PREFIX = 'posthog:boot:'

export function markBootMilestone(milestone: BootMilestone): void {
    try {
        performance.mark(MARK_PREFIX + milestone)
    } catch {
        // A failed mark must not break boot.
    }
}

/** Milliseconds from navigation start to the first mark of each milestone. */
export function bootMilestoneTimings(): Partial<Record<BootMilestone, number>> {
    const timings: Partial<Record<BootMilestone, number>> = {}
    try {
        for (const entry of performance.getEntriesByType('mark')) {
            if (!entry.name.startsWith(MARK_PREFIX)) {
                continue
            }
            const milestone = entry.name.slice(MARK_PREFIX.length) as BootMilestone
            timings[milestone] ??= Math.round(entry.startTime)
        }
    } catch {
        return {}
    }
    return timings
}
