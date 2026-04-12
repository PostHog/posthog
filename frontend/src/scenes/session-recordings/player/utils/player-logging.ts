import { playerConfig } from '@posthog/rrweb'

export type BuiltLogging = {
    logger: playerConfig['logger']
}

export const makeNoOpLogger = (): BuiltLogging => {
    return {
        logger: {
            log: () => {},
            warn: () => {},
        },
    }
}

const IGNORED_WARNING_PREFIXES = ['Could not find node with id']

export function isIgnoredWarning(category: string): boolean {
    return IGNORED_WARNING_PREFIXES.some((prefix) => category.startsWith(prefix))
}

const isPrefixLike = (value: string): boolean => /^\[[^\]]+\]$/.test(value.trim())

function isErrorLike(arg: unknown): arg is { message: string } {
    if (arg instanceof Error) {
        return true
    }
    return arg !== null && typeof arg === 'object' && typeof (arg as { message?: unknown }).message === 'string'
}

export function categorizeWarning(args: any[]): string {
    if (!Array.isArray(args) || args.length === 0) {
        return 'unknown warning'
    }

    const nonPrefixString = args.find((arg) => typeof arg === 'string' && !isPrefixLike(arg)) as string | undefined
    if (typeof nonPrefixString === 'string') {
        const trimmed = nonPrefixString.slice(0, 80).trim()
        const firstSentence = trimmed.split(/[.!?\n]/)[0]
        return firstSentence || trimmed || 'unknown warning'
    }

    const anyError = args.find(isErrorLike)
    if (anyError) {
        return anyError.message.slice(0, 80)
    }

    const anyString = args.find((arg) => typeof arg === 'string') as string | undefined
    if (typeof anyString === 'string') {
        const trimmed = anyString.slice(0, 80).trim()
        const firstSentence = trimmed.split(/[.!?\n]/)[0]
        return firstSentence || trimmed || 'unknown warning'
    }

    return 'unknown warning'
}

export const makeLogger = (onWarning: (category: string) => void): BuiltLogging => {
    ;(window as any)[`__posthog_player_logs`] = (window as any)[`__posthog_player_logs`] || []
    ;(window as any)[`__posthog_player_warnings`] = (window as any)[`__posthog_player_warnings`] || []

    const logStores = {
        log: (window as any)[`__posthog_player_logs`] as any[],
        warning: (window as any)[`__posthog_player_warnings`] as any[],
    }

    return {
        logger: {
            log: (...args: any[]): void => {
                logStores.log.push(args)
            },
            warn: (...args: any[]): void => {
                logStores.warning.push(args)
                const category = categorizeWarning(args)
                if (!isIgnoredWarning(category)) {
                    onWarning(category)
                }
            },
        },
    }
}
