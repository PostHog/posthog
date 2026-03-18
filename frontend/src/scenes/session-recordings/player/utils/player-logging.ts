import { playerConfig } from '@posthog/rrweb'

export type LogType = 'log' | 'warning'
export type LoggingTimers = Record<LogType, NodeJS.Timeout | null>
export type BuiltLogging = {
    logger: playerConfig['logger']
    timers: LoggingTimers
}

export const makeNoOpLogger = (): BuiltLogging => {
    return {
        logger: {
            log: () => {},
            warn: () => {},
        },
        timers: { log: null, warning: null },
    }
}

export const makeLogger = (onIncrement: (count: number) => void): BuiltLogging => {
    const counters = {
        log: 0,
        warning: 0,
    }

    ;(window as any)[`__posthog_player_logs`] = (window as any)[`__posthog_player_logs`] || []
    ;(window as any)[`__posthog_player_warnings`] = (window as any)[`__posthog_player_warnings`] || []

    const logStores: Record<LogType, any[]> = {
        log: (window as any)[`__posthog_player_logs`],
        warning: (window as any)[`__posthog_player_warnings`],
    }

    const timers: LoggingTimers = {
        log: null,
        warning: null,
    }

    const logger = (type: LogType): ((message?: any, ...optionalParams: any[]) => void) => {
        // NOTE: RRWeb can log _alot_ of warnings,
        // so we debounce the count otherwise we just end up making the performance worse
        // We also don't log the messages directly.
        // Sometimes the sheer size of messages and warnings can cause the browser to crash deserializing it all

        return (...args: any[]): void => {
            logStores[type].push(args)
            counters[type] += 1

            if (!timers[type]) {
                timers[type] = setTimeout(() => {
                    timers[type] = null
                    if (type === 'warning') {
                        onIncrement(logStores[type].length)
                    }

                    console.warn(
                        `[PostHog Replayer] ${counters[type]} ${type}s (window.__posthog_player_${type}s to safely log them)`
                    )
                    counters[type] = 0
                }, 5000)
            }
        }
    }

    return {
        logger: {
            log: logger('log'),
            warn: logger('warning'),
        },
        timers,
    }
}
