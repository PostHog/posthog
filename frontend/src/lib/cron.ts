import { CronExpressionParser } from 'cron-parser'
import cronstrue from 'cronstrue'

/** Every schedule we accept is a standard 5-field expression: minute hour day-of-month month day-of-week. */
const CRON_FIELD_COUNT = 5

function hasFiveFields(expr: string): boolean {
    return expr.trim().split(/\s+/).length === CRON_FIELD_COUNT
}

/** Human-readable description of a 5-field cron expression, or an error string. Returns null for empty input. */
export function describeCron(expr: string | null | undefined): string | null {
    if (!expr) {
        return null
    }
    if (!hasFiveFields(expr)) {
        return 'Invalid cron expression'
    }
    try {
        // Validate with cron-parser first — cronstrue is lenient and can
        // produce garbled output (e.g. "Monday through undefined") for
        // syntactically incomplete expressions like "0 9 * * 1-".
        CronExpressionParser.parse(expr)
        return cronstrue.toString(expr)
    } catch {
        return 'Invalid cron expression'
    }
}

/**
 * The next time a cron expression fires, evaluated in `timezone` — which must be the project's,
 * because that is what the scheduler evaluates cron schedules in. Null when the expression is
 * unparseable, so callers can fall back rather than render a wrong time.
 */
export function nextCronOccurrence(expr: string | null | undefined, timezone: string, from?: Date): Date | null {
    if (!expr || !hasFiveFields(expr)) {
        return null
    }
    try {
        return CronExpressionParser.parse(expr, { currentDate: from ?? new Date(), tz: timezone })
            .next()
            .toDate()
    } catch {
        return null
    }
}
