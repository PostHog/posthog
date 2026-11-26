interface RealProcess {
    env: Record<string, string | undefined>
}

/**
 * Runs `run` with the process in `timezone`, then puts the timezone back. Jest hands a test a copy of `process.env`,
 * and only a write to the real one changes the zone that `Date` reads, so the real process is fetched from outside the
 * test's sandbox.
 */
export function withTimezone(timezone: string, run: () => void): void {
    const realProcess: RealProcess = jest.requireActual('vm').runInThisContext('process')
    const previous = realProcess.env.TZ
    realProcess.env.TZ = timezone
    try {
        run()
    } finally {
        realProcess.env.TZ = previous
    }
}
