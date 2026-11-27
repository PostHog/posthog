import type { QueryOutcome, QueryTiming } from '../../panels/core/panelHostContext'

/** What started a load: opening the dashboard, a refresh, a filter or time range change, or another tab. */
export type DashboardLoadTrigger = 'load' | 'refresh' | 'filters' | 'tab'

export type DashboardLoadReport = {
    trigger: DashboardLoadTrigger
    /** `abandoned` when the person left, or another load began, before every query in range ended. */
    status: 'success' | 'abandoned'
    durationMs: number
    firstResultMs: number | null
    queryCount: number
    cachedQueryCount: number
    failedQueryCount: number
    slowestQueryMs: number | null
    /** Main-thread tasks over 50 ms, which is what makes a loading dashboard feel stuck. Chromium only. */
    longTaskCount: number | null
    longTaskMs: number | null
    /** A hidden page throttles timers and frames, so its timings are not comparable. */
    pageHidden: boolean
}

export type DashboardTiming = QueryTiming & {
    begin: (trigger: DashboardLoadTrigger) => void
    dispose: () => void
}

/** A tile mounts a frame or two after it comes into range, so a load ends only after this long with no query running. */
const QUIET_MS = 100

type Load = {
    trigger: DashboardLoadTrigger
    startedAt: number
    lastEndedAt: number
    firstResultAt: number | null
    pending: number
    queryCount: number
    cachedQueryCount: number
    failedQueryCount: number
    slowestQueryMs: number | null
    longTaskCount: number
    longTaskMs: number
    pageHidden: boolean
    stop: () => void
}

function supportsLongTasks(): boolean {
    return typeof PerformanceObserver !== 'undefined' && !!PerformanceObserver.supportedEntryTypes?.includes('longtask')
}

/**
 * Times each load from its trigger until every query of the tiles in range has ended and no tile is waiting to mount.
 * Queries that start while no load is open, such as from scrolling, are not timed.
 */
export function createDashboardTiming({
    isSettled,
    onReport,
    now = () => performance.now(),
}: {
    isSettled: () => boolean
    onReport: (report: DashboardLoadReport) => void
    now?: () => number
}): DashboardTiming {
    let load: Load | null = null
    let quietTimer: ReturnType<typeof setTimeout> | undefined

    const finish = (status: DashboardLoadReport['status']): void => {
        clearTimeout(quietTimer)
        const ended = load
        if (!ended) {
            return
        }
        load = null
        ended.stop()
        if (ended.queryCount === 0) {
            return
        }
        const endedAt = status === 'abandoned' ? now() : ended.lastEndedAt
        const longTasks = supportsLongTasks()
        try {
            performance.measure(`dashboard v2 ${ended.trigger}`, { start: ended.startedAt, end: endedAt })
        } catch {
            // Only a trace in DevTools reads the measure, so a browser without it loses nothing.
        }
        onReport({
            trigger: ended.trigger,
            status,
            durationMs: Math.round(endedAt - ended.startedAt),
            firstResultMs: ended.firstResultAt === null ? null : Math.round(ended.firstResultAt - ended.startedAt),
            queryCount: ended.queryCount,
            cachedQueryCount: ended.cachedQueryCount,
            failedQueryCount: ended.failedQueryCount,
            slowestQueryMs: ended.slowestQueryMs === null ? null : Math.round(ended.slowestQueryMs),
            longTaskCount: longTasks ? ended.longTaskCount : null,
            longTaskMs: longTasks ? Math.round(ended.longTaskMs) : null,
            pageHidden: ended.pageHidden,
        })
    }

    const waitForQuiet = (): void => {
        clearTimeout(quietTimer)
        quietTimer = setTimeout(() => {
            if (!load || load.pending > 0) {
                return
            }
            if (isSettled()) {
                finish('success')
            } else {
                waitForQuiet()
            }
        }, QUIET_MS)
    }

    const watch = (current: Load): (() => void) => {
        const stops: (() => void)[] = []
        if (supportsLongTasks()) {
            const observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    current.longTaskCount++
                    current.longTaskMs += entry.duration
                }
            })
            observer.observe({ type: 'longtask' })
            stops.push(() => observer.disconnect())
        }
        if (typeof document !== 'undefined') {
            const onVisibility = (): void => {
                current.pageHidden ||= document.visibilityState === 'hidden'
            }
            onVisibility()
            document.addEventListener('visibilitychange', onVisibility)
            stops.push(() => document.removeEventListener('visibilitychange', onVisibility))
        }
        return () => stops.forEach((stop) => stop())
    }

    return {
        begin(trigger) {
            finish('abandoned')
            const startedAt = now()
            const current: Load = {
                trigger,
                startedAt,
                lastEndedAt: startedAt,
                firstResultAt: null,
                pending: 0,
                queryCount: 0,
                cachedQueryCount: 0,
                failedQueryCount: 0,
                slowestQueryMs: null,
                longTaskCount: 0,
                longTaskMs: 0,
                pageHidden: false,
                stop: () => {},
            }
            current.stop = watch(current)
            load = current
            waitForQuiet()
        },
        started(cached) {
            const current = load
            if (!current) {
                return () => {}
            }
            clearTimeout(quietTimer)
            const startedAt = now()
            current.pending++
            current.queryCount++
            if (cached) {
                current.cachedQueryCount++
            }
            let ended = false
            return (outcome: QueryOutcome) => {
                if (ended || load !== current) {
                    return
                }
                ended = true
                const endedAt = now()
                current.pending--
                current.lastEndedAt = endedAt
                current.firstResultAt ??= endedAt
                current.slowestQueryMs = Math.max(current.slowestQueryMs ?? 0, endedAt - startedAt)
                if (outcome === 'error') {
                    current.failedQueryCount++
                }
                if (current.pending === 0) {
                    waitForQuiet()
                }
            }
        },
        hold() {
            const current = load
            if (!current) {
                return () => {}
            }
            clearTimeout(quietTimer)
            current.pending++
            let released = false
            return () => {
                if (released || load !== current) {
                    return
                }
                released = true
                current.pending--
                if (current.pending === 0) {
                    waitForQuiet()
                }
            }
        },
        dispose() {
            finish('abandoned')
        },
    }
}
