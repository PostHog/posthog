/**
 * Process-wide structured logger — pino under the hood, exposed as a small
 * `createLogger(name)` factory. Every v2 service should obtain its logger this
 * way so we end up with consistent JSON in prod and pretty output in dev,
 * driven by a single `LOG_LEVEL` env var.
 *
 *   import { createLogger } from '@posthog/agent-shared'
 *   const log = createLogger('runner')
 *   log.debug({ session_id, turn }, 'pi invoke')
 *   log.error({ err, session_id }, 'session crashed')
 *
 * Defaults:
 *   - Tests (vitest sets VITEST=true): `warn` — keeps test output clean.
 *     Override per-run with `LOG_LEVEL=debug pnpm test`.
 *   - Production (`NODE_ENV=production`): JSON to stdout, level `info`.
 *   - Dev / local: pretty-printed via `pino-pretty`, level `info`.
 *
 * Use child loggers liberally (`log.child({ session_id })`) so call sites
 * don't have to repeat shared context — every record carries the bindings.
 */

import pino, { Logger as PinoLogger } from 'pino'

export type Logger = PinoLogger

/**
 * Documented exception to the "no process.env outside the typed config loader"
 * rule (agent-shared/CLAUDE.md rule 7). The logger is the bootstrap — it
 * needs a level before any service has loaded its config, and importing the
 * config schema from here would create a circular dependency (every config
 * loader logs validation errors). Tests are caught by `VITEST=true`, which
 * vitest sets automatically; prod sets `LOG_LEVEL=info` via the chart.
 */
function defaultLevel(): string {
    if (process.env.LOG_LEVEL) {
        return process.env.LOG_LEVEL
    }
    if (process.env.VITEST || process.env.NODE_ENV === 'test') {
        return 'warn'
    }
    return 'info'
}

let rootLogger: Logger | null = null

function getRoot(): Logger {
    if (rootLogger) {
        return rootLogger
    }
    const isProd = process.env.NODE_ENV === 'production'
    // Pretty output everywhere except prod. Test runs get pretty too — easier
    // to scan when `LOG_LEVEL=debug` is on.
    const transport = isProd
        ? undefined
        : {
              target: 'pino-pretty',
              options: { colorize: true, ignore: 'pid,hostname', translateTime: 'HH:MM:ss.l' },
          }
    rootLogger = pino({ level: defaultLevel(), transport })
    return rootLogger
}

/**
 * Create a named logger. `name` becomes a `name` binding on every record so
 * subsystems are easy to filter (e.g. `| jq 'select(.name=="runner")'`).
 * Optional `bindings` attach extra context (commonly `session_id`, `team_id`).
 */
export function createLogger(name: string, bindings?: Record<string, unknown>): Logger {
    return getRoot().child({ name, ...bindings })
}
