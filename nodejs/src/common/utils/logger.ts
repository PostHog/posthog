import { isSpanContextValid, trace } from '@opentelemetry/api'
import pino from 'pino'

import type { LogLevel } from '~/types'

import { isProdEnv, isTestEnv } from './env-utils'

// Read from env directly instead of defaultConfig: that module throws at import when
// Postgres env vars are missing, and entrypoints without them (e.g. the recording
// rasterizer) reach this logger transitively.
const logLevel: LogLevel = (process.env.LOG_LEVEL as LogLevel) || (isTestEnv() ? 'warn' : 'info')

// Correlate log lines with the active OTel trace, using the same `trace_id`/`span_id` keys as the
// Django logger so the log collector links them to their trace. Read at emit time so nested spans get
// the right span_id; a no-op when no valid span is in scope (e.g. tracing disabled).
function activeTraceContext(): { trace_id: string; span_id: string } | undefined {
    const spanContext = trace.getActiveSpan()?.spanContext()
    if (!spanContext || !isSpanContextValid(spanContext)) {
        return undefined
    }
    return { trace_id: spanContext.traceId, span_id: spanContext.spanId }
}

export class Logger {
    private pino: ReturnType<typeof pino>
    private prefix: string
    private transport?: ReturnType<typeof pino.transport>
    private isShutdown: boolean = false

    constructor(name: string) {
        this.prefix = `[${name.toUpperCase()}]`
        if (isProdEnv()) {
            this.pino = pino({
                // By default pino will log the level number. So we can easily unify
                // the log structure with other parts of the app e.g. the web
                // server, we output the level name rather than the number. This
                // way, e.g. we can easily ingest into Loki and query across
                // workloads for all `error` log levels.
                formatters: {
                    level: (label) => {
                        return { level: label }
                    },
                },
                level: logLevel,
            })
        } else {
            // If we're not in production, we ensure that:
            //
            //  1. we see debug logs
            //  2. logs are pretty printed
            //
            // NOTE: we keep a reference to the transport such that we can call
            // end on it, otherwise Jest will hang on open handles.
            this.transport = pino.transport({
                target: 'pino-pretty',
                options: {
                    sync: true,
                    level: logLevel,
                },
            })
            this.pino = pino({ level: logLevel }, this.transport)
        }
    }

    private _log(level: LogLevel, ...args: any[]) {
        // Prevent logging after shutdown to avoid "worker has exited" errors
        if (this.isShutdown || !this.pino) {
            return
        }

        // Get the last arg - if it is an object then we spread it into our log values
        const lastArg = args[args.length - 1]
        // Check if it is an object and not an error
        const extra = typeof lastArg === 'object' && !(lastArg instanceof Error) ? lastArg : undefined

        // If there is an extra object, we spread it into our log values
        if (extra) {
            args.pop()
        }

        const msg = `${this.prefix} ${args.join(' ')}`

        try {
            this.pino[level]({
                ...activeTraceContext(),
                ...(extra || {}),
                msg,
            })
        } catch (error) {
            // Ignore errors during logging if logger is shutting down
            if (error.message?.includes('worker has exited')) {
                return
            }
            throw error
        }
    }

    debug(...args: any[]) {
        this._log('debug', ...args)
    }

    info(...args: any[]) {
        this._log('info', ...args)
    }

    warn(...args: any[]) {
        this._log('warn', ...args)
    }

    error(...args: any[]) {
        this._log('error', ...args)
    }

    async shutdown(): Promise<void> {
        this.isShutdown = true
        try {
            if (this.transport) {
                await this.transport.end()
            }
        } catch {
            // Ignore errors during shutdown as the transport may already be closed
            // This prevents Jest from hanging on unhandled errors during teardown
        }
    }
}

export const logger = new Logger(process.env.PLUGIN_SERVER_MODE ?? 'MAIN')

export function serializeError(error: unknown): Record<string, unknown> | unknown {
    if (error instanceof Error) {
        return { name: error.name, message: error.message, stack: error.stack }
    }
    return error
}

export async function shutdownLogger(): Promise<void> {
    await logger.shutdown()
}
