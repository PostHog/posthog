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

import os from 'node:os'
import path from 'node:path'
import pino, { Logger as PinoLogger } from 'pino'

export type Logger = PinoLogger

/**
 * Dev-only: where each service tees its JSON logs so a local agent (or you) can
 * read them without scraping the mprocs pane. `AGENT_LOG_FILE` is set per service
 * in `bin/mprocs.yaml`; the shared fallback is fine for a single ad-hoc process.
 * See products/agent_platform/AGENTS.md.
 */
function devLogFile(): string {
    return process.env.AGENT_LOG_FILE || path.join(os.tmpdir(), 'posthog-agent-logs', 'agent.log')
}

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
    const isTest = !!process.env.VITEST || process.env.NODE_ENV === 'test'
    // Prod: JSON to stdout (no transport). Dev/test: pretty to stdout. Dev only
    // (not test): ALSO tee raw JSON to a tmp file so a local agent can `tail`/grep
    // the logs — separate worker target, doesn't touch the pretty stdout stream.
    const level = defaultLevel()
    const targets: pino.TransportTargetOptions[] = []
    if (!isProd) {
        targets.push({
            target: 'pino-pretty',
            level,
            options: { colorize: true, ignore: 'pid,hostname', translateTime: 'HH:MM:ss.l' },
        })
    }
    if (!isProd && !isTest) {
        targets.push({ target: 'pino/file', level, options: { destination: devLogFile(), mkdir: true } })
    }
    const transport = targets.length > 0 ? { targets } : undefined
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
