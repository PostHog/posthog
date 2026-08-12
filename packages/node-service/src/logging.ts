import { pino, stdSerializers, type DestinationStream, type Logger, type LoggerOptions } from 'pino'

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'
export type ServiceLogger = Logger

export interface CreateLoggerOptions {
    serviceName: string
    level?: LogLevel
    destination?: DestinationStream
}

export function createLogger(options: CreateLoggerOptions): Logger {
    const loggerOptions: LoggerOptions = {
        level: options.level ?? 'info',
        base: { service: options.serviceName },
        formatters: {
            level: (level) => ({ level }),
        },
        serializers: {
            err: stdSerializers.err,
            error: stdSerializers.err,
        },
    }

    return options.destination ? pino(loggerOptions, options.destination) : pino(loggerOptions)
}

export function serializeError(error: unknown): Record<string, unknown> {
    if (error instanceof Error) {
        return {
            name: error.name,
            message: error.message,
            stack: error.stack,
        }
    }

    return { message: String(error) }
}
