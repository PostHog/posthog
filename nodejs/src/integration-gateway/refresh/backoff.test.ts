import {
    REFRESH_BACKOFF_BASE_SECONDS,
    REFRESH_TERMINAL_FAILURE_COUNT,
    recordRefreshFailure,
    recordRefreshSuccess,
    refreshBackoffActive,
    refreshFailureReason,
} from './backoff'
import { nowSecs } from './expiry'

describe('refreshFailureReason', () => {
    it.each<[string, number | null, any, string, string]>([
        ['null status is network', null, {}, 'hubspot', 'network'],
        ['invalid_grant', 400, { error: 'invalid_grant' }, 'hubspot', 'invalid_grant'],
        ['invalid_client', 401, { error: 'invalid_client' }, 'hubspot', 'invalid_client'],
        ['5xx is http_5xx', 503, { error: 'server_error' }, 'hubspot', 'http_5xx'],
        ['other 4xx is other', 400, { error: 'something_else' }, 'hubspot', 'other'],
        ['reddit 400 with error:400 is invalid_grant', 400, { error: 400 }, 'reddit-ads', 'invalid_grant'],
        ['non-reddit 400 with error:400 is other', 400, { error: 400 }, 'hubspot', 'other'],
    ])('%s', (_name, status, body, kind, expected) => {
        expect(refreshFailureReason(status, body, kind)).toBe(expected)
    })
})

describe('recordRefreshFailure', () => {
    it('does not mutate the input config', () => {
        const config = { refreshed_at: 1 }
        recordRefreshFailure(config, 'other')
        expect(config).toEqual({ refreshed_at: 1 })
    })

    it('bumps the failure count and schedules exponential backoff', () => {
        const first = recordRefreshFailure({}, 'http_5xx')
        expect(first.refresh_failure_count).toBe(1)
        expect(first.refresh_next_attempt_at).toBeGreaterThan(nowSecs())

        const second = recordRefreshFailure(first, 'http_5xx')
        expect(second.refresh_failure_count).toBe(2)
        // Backoff at least doubles the base between the first and second failure.
        const firstDelay = first.refresh_next_attempt_at - Math.floor(nowSecs())
        const secondDelay = second.refresh_next_attempt_at - Math.floor(nowSecs())
        expect(secondDelay).toBeGreaterThan(firstDelay)
        expect(firstDelay).toBeGreaterThanOrEqual(REFRESH_BACKOFF_BASE_SECONDS - 1)
    })

    it('goes terminal only after an unbroken invalid_grant streak', () => {
        let config: Record<string, any> = {}
        for (let i = 1; i < REFRESH_TERMINAL_FAILURE_COUNT; i++) {
            config = recordRefreshFailure(config, 'invalid_grant')
            expect(config.refresh_terminal).toBeUndefined()
        }
        config = recordRefreshFailure(config, 'invalid_grant')
        expect(config.refresh_invalid_grant_count).toBe(REFRESH_TERMINAL_FAILURE_COUNT)
        expect(config.refresh_terminal).toBe(true)
    })

    it('a non-grant failure resets the invalid_grant streak (no terminal)', () => {
        let config: Record<string, any> = {}
        for (let i = 0; i < REFRESH_TERMINAL_FAILURE_COUNT - 1; i++) {
            config = recordRefreshFailure(config, 'invalid_grant')
        }
        // A transient 5xx amid the streak clears it, so the next invalid_grant can't tip it terminal.
        config = recordRefreshFailure(config, 'http_5xx')
        expect(config.refresh_invalid_grant_count).toBeUndefined()
        config = recordRefreshFailure(config, 'invalid_grant')
        expect(config.refresh_invalid_grant_count).toBe(1)
        expect(config.refresh_terminal).toBeUndefined()
    })
})

describe('recordRefreshSuccess', () => {
    it('clears all backoff/terminal state but keeps other config', () => {
        const cleared = recordRefreshSuccess({
            refreshed_at: 5,
            expires_in: 3600,
            refresh_failure_count: 3,
            refresh_invalid_grant_count: 2,
            refresh_next_attempt_at: nowSecs() + 100,
            refresh_terminal: true,
        })
        expect(cleared).toEqual({ refreshed_at: 5, expires_in: 3600 })
    })
})

describe('refreshBackoffActive', () => {
    it('is true when terminal', () => {
        expect(refreshBackoffActive({ refresh_terminal: true })).toBe(true)
    })
    it('is true inside the backoff window, false once elapsed', () => {
        expect(refreshBackoffActive({ refresh_next_attempt_at: nowSecs() + 100 })).toBe(true)
        expect(refreshBackoffActive({ refresh_next_attempt_at: nowSecs() - 100 })).toBe(false)
    })
    it('is false with no backoff state', () => {
        expect(refreshBackoffActive({})).toBe(false)
    })
})
