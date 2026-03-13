import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

type LogLevel = 'info' | 'warn' | 'error' | 'debug'

const SEVERITY_MAP: Record<LogLevel, { text: string; number: number }> = {
    debug: { text: 'DEBUG', number: 5 },
    info: { text: 'INFO', number: 9 },
    warn: { text: 'WARN', number: 13 },
    error: { text: 'ERROR', number: 17 },
}

/**
 * Structured logger for the toolbar. Logs to the browser console and sends
 * log records to PostHog's /i/v1/logs endpoint (OTLP format).
 *
 * Usage:
 *   toolbarLogger.warn('auth', 'PKCE verifier expired', { ttl_ms: PKCE_TTL_MS })
 */
export const toolbarLogger = {
    debug(context: string, message: string, properties?: Record<string, unknown>): void {
        log('debug', context, message, properties)
    },
    info(context: string, message: string, properties?: Record<string, unknown>): void {
        log('info', context, message, properties)
    },
    warn(context: string, message: string, properties?: Record<string, unknown>): void {
        log('warn', context, message, properties)
    },
    error(context: string, message: string, properties?: Record<string, unknown>): void {
        log('error', context, message, properties)
    },
}

function toAttributeValue(value: unknown): Record<string, unknown> {
    if (typeof value === 'string') {
        return { stringValue: value }
    }
    if (typeof value === 'number') {
        return Number.isInteger(value) ? { intValue: value } : { doubleValue: value }
    }
    if (typeof value === 'boolean') {
        return { boolValue: value }
    }
    return { stringValue: String(value) }
}

function toAttributes(props: Record<string, unknown>): Array<{ key: string; value: Record<string, unknown> }> {
    return Object.entries(props).map(([key, value]) => ({
        key,
        value: toAttributeValue(value),
    }))
}

function hrTimeNano(): string {
    const nowMs = Date.now()
    const seconds = Math.trunc(nowMs / 1000)
    const nanos = (nowMs % 1000) * 1_000_000
    return String(BigInt(seconds) * BigInt(1_000_000_000) + BigInt(nanos))
}

function sendLog(level: LogLevel, context: string, message: string, properties?: Record<string, unknown>): void {
    const config = toolbarPosthogJS.config
    const apiHost = config.api_host?.replace(/\/+$/, '') || ''
    const token = config.token

    if (!apiHost || !token) {
        return
    }

    const severity = SEVERITY_MAP[level]
    const timeNano = hrTimeNano()

    const attributes = toAttributes({
        'toolbar.context': context,
        'service.name': 'posthog-toolbar',
        ...properties,
    })

    const body = {
        resourceLogs: [
            {
                resource: {
                    attributes: toAttributes({
                        'service.name': 'posthog-toolbar',
                        host: window.location.host,
                    }),
                },
                scopeLogs: [
                    {
                        scope: { name: 'toolbar' },
                        logRecords: [
                            {
                                timeUnixNano: timeNano,
                                observedTimeUnixNano: timeNano,
                                severityNumber: severity.number,
                                severityText: severity.text,
                                body: { stringValue: message },
                                attributes,
                            },
                        ],
                    },
                ],
            },
        ],
    }

    const url = `${apiHost}/i/v1/logs?token=${token}`

    if (navigator.sendBeacon) {
        navigator.sendBeacon(url, JSON.stringify(body))
    } else {
        void fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            keepalive: true,
        })
    }
}

function log(level: LogLevel, context: string, message: string, properties?: Record<string, unknown>): void {
    const prefix = `[PostHog Toolbar][${context}]`
    const args: unknown[] = [`${prefix} ${message}`]

    if (properties && Object.keys(properties).length > 0) {
        args.push(properties)
    }

    if (level === 'error') {
        console.error(...args)
    } else if (level === 'warn') {
        console.warn(...args)
    } else if (level === 'debug') {
    } else {
        console.info(...args)
    }

    sendLog(level, context, message, properties)
}
