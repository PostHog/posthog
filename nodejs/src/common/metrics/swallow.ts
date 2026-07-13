/**
 * Telemetry recorders run in finally blocks, error handlers, and stats callbacks of
 * hot paths — a throw there would mask the real error (or DLQ a message with the
 * wrong reason), so recording failures are swallowed.
 */
export function swallowing<Args extends unknown[]>(record: (...args: Args) => void): (...args: Args) => void {
    return (...args: Args): void => {
        try {
            record(...args)
        } catch {
            // never let telemetry break the caller
        }
    }
}
