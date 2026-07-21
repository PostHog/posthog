/**
 * Validated env-var tunables. The scrub knobs are correctness-critical: a typo'd value that parses
 * to NaN fails OPEN (e.g. `prob >= NaN` is always false -> zero text boxes -> un-redacted output,
 * silently counted as scrubbed). So every numeric knob must parse finite and in range, at module
 * load, or the process refuses to start.
 */
export function numFromEnv(name: string, defaultValue: number, min: number, max: number): number {
    const raw = process.env[name]
    const value = raw === undefined ? defaultValue : Number(raw)
    if (!Number.isFinite(value) || value < min || value > max) {
        throw new Error(`${name} must be a number in [${min}, ${max}], got ${raw ?? defaultValue}`)
    }
    return value
}
