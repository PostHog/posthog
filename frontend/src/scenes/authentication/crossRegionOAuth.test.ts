import { Region } from '~/types'

import { buildRegionSwitchUrl, translateClientIdForRegion } from './crossRegionOAuth'

const POSTHOG_CODE_US_CLIENT_ID = 'HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W'
const POSTHOG_CODE_EU_CLIENT_ID = 'AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9'

describe('translateClientIdForRegion', () => {
    test('translates US → EU for known first-party clients', () => {
        expect(translateClientIdForRegion(POSTHOG_CODE_US_CLIENT_ID, Region.EU)).toBe(POSTHOG_CODE_EU_CLIENT_ID)
    })

    test('translates EU → US for known first-party clients', () => {
        expect(translateClientIdForRegion(POSTHOG_CODE_EU_CLIENT_ID, Region.US)).toBe(POSTHOG_CODE_US_CLIENT_ID)
    })

    test('returns the same client_id when target region matches existing region', () => {
        expect(translateClientIdForRegion(POSTHOG_CODE_US_CLIENT_ID, Region.US)).toBe(POSTHOG_CODE_US_CLIENT_ID)
    })

    test('passes through unknown client_ids unchanged (third-party apps)', () => {
        expect(translateClientIdForRegion('not-a-known-client', Region.EU)).toBe('not-a-known-client')
    })
})

describe('buildRegionSwitchUrl', () => {
    test('rewrites client_id when path is /oauth/authorize directly', () => {
        const url = buildRegionSwitchUrl({
            targetHost: 'eu.posthog.com',
            pathname: '/oauth/authorize',
            search: `?client_id=${POSTHOG_CODE_US_CLIENT_ID}&response_type=code`,
            hash: '',
            targetRegion: Region.EU,
        })
        expect(url).toBe(
            `https://eu.posthog.com/oauth/authorize?client_id=${POSTHOG_CODE_EU_CLIENT_ID}&response_type=code`
        )
    })

    test('rewrites client_id inside next= when bouncing through /login', () => {
        const next = `/oauth/authorize?client_id=${POSTHOG_CODE_US_CLIENT_ID}&response_type=code&state=abc`
        const url = buildRegionSwitchUrl({
            targetHost: 'eu.posthog.com',
            pathname: '/login',
            search: `?next=${encodeURIComponent(next)}`,
            hash: '',
            targetRegion: Region.EU,
        })
        const decodedNext = new URLSearchParams(new URL(url).search).get('next')!
        const innerParams = new URLSearchParams(decodedNext.split('?')[1])
        expect(innerParams.get('client_id')).toBe(POSTHOG_CODE_EU_CLIENT_ID)
        expect(innerParams.get('response_type')).toBe('code')
        expect(innerParams.get('state')).toBe('abc')
    })

    test('leaves unrelated URLs untouched', () => {
        const url = buildRegionSwitchUrl({
            targetHost: 'eu.posthog.com',
            pathname: '/dashboard',
            search: '?foo=bar',
            hash: '#section',
            targetRegion: Region.EU,
        })
        expect(url).toBe('https://eu.posthog.com/dashboard?foo=bar#section')
    })

    test('does not rewrite unknown client_ids on /oauth/authorize', () => {
        const url = buildRegionSwitchUrl({
            targetHost: 'eu.posthog.com',
            pathname: '/oauth/authorize',
            search: '?client_id=third-party-id&response_type=code',
            hash: '',
            targetRegion: Region.EU,
        })
        expect(url).toBe('https://eu.posthog.com/oauth/authorize?client_id=third-party-id&response_type=code')
    })

    test('preserves hash and other params on /login?next=...', () => {
        const next = `/oauth/authorize?client_id=${POSTHOG_CODE_US_CLIENT_ID}`
        const url = buildRegionSwitchUrl({
            targetHost: 'eu.posthog.com',
            pathname: '/login',
            search: `?next=${encodeURIComponent(next)}&error=some_error`,
            hash: '#anchor',
            targetRegion: Region.EU,
        })
        expect(url).toContain('https://eu.posthog.com/login?')
        expect(url).toContain('error=some_error')
        expect(url).toContain(encodeURIComponent(POSTHOG_CODE_EU_CLIENT_ID))
        expect(url.endsWith('#anchor')).toBe(true)
    })
})
