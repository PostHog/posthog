/**
 * Legacy test utilities from the deprecated @posthog/plugin-scaffold package (v1.4.4).
 * Only used by legacy plugin tests.
 *
 * These utilities are loosely typed (returning `any`) to match the behavior of the
 * original untyped JavaScript module.
 */
import { parseJSON } from '~/utils/json-parse'

export function createEvent(changes: Record<string, any> = {}): any {
    return {
        distinct_id: '007',
        ip: '127.128.129.130',
        site_url: 'http://localhost:8000/',
        team_id: 13,
        now: '2020-11-26T12:58:57.367Z',
        event: 'EVENT_TYPE',
        sent_at: '2020-11-26T12:58:58.453Z',
        timestamp: '2020-11-26T12:58:58.453Z',
        uuid: '',
        ...changes,
    }
}

export function createPageview(): any {
    return createEvent({
        event: '$pageview',
        properties: {
            $os: 'Mac OS X',
            $lib: 'web',
            $host: 'localhost:8000',
            $time: 1606383312.494,
            token: 'mre13a_SMBv9EwHAtdtTyutyy6AfO00OTPwaalaHPGgKLS',
            $browser: 'Chrome',
            $user_id: '3erf45reXthrGser675waeHFAsbv4AsadfR',
            $pathname: '/instance/status',
            $device_id: '17554768afe5cb-0fc915d2a583cf-166f6152-1ea000-175543686ffdc5',
            $insert_id: 'hgu2p36uvlc1b9dg',
            distinct_id: 'scbbAqF7uyrMmamV4QBzcA1rrm9wHNISdFweZz-mQ0',
            $current_url: 'http://localhost:8000/instance/status',
            $lib_version: '1.7.0-beta.1',
            $screen_width: 1790,
            $screen_height: 1120,
            posthog_version: '1.17.0',
            $browser_version: 86,
            $initial_referrer: '$direct',
            has_slack_webhook: false,
            $active_feature_flags: ['navigation-1775', 'session-recording-player'],
            $initial_referring_domain: '$direct',
        },
    })
}

export function createIdentify(): any {
    return createEvent({
        event: '$identify',
        $set: {
            $os: 'Mac OS X',
            email: 'test@posthog.com',
            $browser: 'Chrome',
            $browser_version: 86,
            $initial_referrer: '$direct',
            $initial_referring_domain: '$direct',
        },
    })
}

export function clone<T>(object: T): T {
    return parseJSON(JSON.stringify(object))
}

export function createCache(): {
    set: (key: string, value: any) => void
    get: (key: string, defaultValue: any) => Promise<any>
} {
    const cache: Record<string, any> = {}
    return {
        set: (key: string, value: any) => {
            cache[key] = value
        },
        // eslint-disable-next-line @typescript-eslint/require-await
        get: async (key: string, defaultValue: any) => {
            if (typeof cache[key] === 'undefined') {
                return defaultValue
            }
            return cache[key]
        },
    }
}

let testMeta: any = {
    config: {},
    cache: createCache(),
    storage: createCache(),
    global: {},
    attachments: {},
}

export function resetMeta(meta: Record<string, any> = {}): any {
    testMeta = {
        config: {},
        cache: createCache(),
        storage: createCache(),
        global: {},
        attachments: {},
        ...meta,
    }
    return testMeta
}

export function getMeta(): any {
    return testMeta
}
