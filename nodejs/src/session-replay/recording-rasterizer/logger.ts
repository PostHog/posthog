import pino from 'pino'

import { config } from './config'

export type Logger = pino.Logger

const rootLogger = pino({
    level: config.logLevel,
    formatters: {
        level: (label) => ({ level: label }),
    },
    base: { source: 'rasterizer' },
    timestamp: pino.stdTimeFunctions.isoTime,
})

export function createLogger(bindings: Record<string, unknown> = {}): Logger {
    return Object.keys(bindings).length ? rootLogger.child(bindings) : rootLogger
}
