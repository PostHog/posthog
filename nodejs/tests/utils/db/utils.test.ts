import { personInitialAndUTMProperties } from '../../../src/utils/db/utils'

describe('personInitialAndUTMProperties()', () => {
    it('adds initial and utm properties', () => {
        const properties = {
            distinct_id: 2,
            $browser: 'Chrome',
            $current_url: 'https://test.com',
            $os: 'Mac OS X',
            $os_version: '10.15.7',
            $browser_version: '95',
            $referring_domain: 'https://google.com',
            $referrer: 'https://google.com/?q=posthog',
            utm_medium: 'twitter',
            gclid: 'GOOGLE ADS ID',
            msclkid: 'BING ADS ID',
            $elements: [
                { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
            ],
            $app_build: 2,
            $app_name: 'my app',
            $app_namespace: 'com.posthog.myapp',
            $app_version: '1.2.3',
            $set: { $browser_version: 'manually $set value wins' },
            $set_once: { $initial_os_version: 'manually $set_once value wins' },
        }
        expect(personInitialAndUTMProperties(properties)).toMatchInlineSnapshot(
            `
            {
              "$app_build": 2,
              "$app_name": "my app",
              "$app_namespace": "com.posthog.myapp",
              "$app_version": "1.2.3",
              "$browser": "Chrome",
              "$browser_version": "95",
              "$current_url": "https://test.com",
              "$elements": [
                {
                  "attr__class": "btn btn-sm",
                  "nth_child": 1,
                  "nth_of_type": 2,
                  "tag_name": "a",
                },
                {
                  "$el_text": "💻",
                  "nth_child": 1,
                  "nth_of_type": 2,
                  "tag_name": "div",
                },
              ],
              "$os": "Mac OS X",
              "$os_version": "10.15.7",
              "$referrer": "https://google.com/?q=posthog",
              "$referring_domain": "https://google.com",
              "$set": {
                "$app_build": 2,
                "$app_name": "my app",
                "$app_namespace": "com.posthog.myapp",
                "$app_version": "1.2.3",
                "$browser": "Chrome",
                "$browser_version": "manually $set value wins",
                "$current_url": "https://test.com",
                "$os": "Mac OS X",
                "$os_version": "10.15.7",
                "$referrer": "https://google.com/?q=posthog",
                "$referring_domain": "https://google.com",
                "gclid": "GOOGLE ADS ID",
                "msclkid": "BING ADS ID",
                "utm_medium": "twitter",
              },
              "$set_once": {
                "$initial_app_build": 2,
                "$initial_app_name": "my app",
                "$initial_app_namespace": "com.posthog.myapp",
                "$initial_app_version": "1.2.3",
                "$initial_browser": "Chrome",
                "$initial_browser_version": "95",
                "$initial_current_url": "https://test.com",
                "$initial_gclid": "GOOGLE ADS ID",
                "$initial_msclkid": "BING ADS ID",
                "$initial_os": "Mac OS X",
                "$initial_os_version": "manually $set_once value wins",
                "$initial_referrer": "https://google.com/?q=posthog",
                "$initial_referring_domain": "https://google.com",
                "$initial_utm_medium": "twitter",
              },
              "distinct_id": 2,
              "gclid": "GOOGLE ADS ID",
              "msclkid": "BING ADS ID",
              "utm_medium": "twitter",
            }
        `
        )
    })
    it('initial current domain regression test', () => {
        const properties = { $current_url: 'https://test.com' }
        expect(personInitialAndUTMProperties(properties)).toEqual({
            $current_url: 'https://test.com',
            $set_once: { $initial_current_url: 'https://test.com' },
            $set: { $current_url: 'https://test.com' },
        })
    })
    it('treats $os_name as fallback for $os', () => {
        const propertiesOsNameOnly = { $os_name: 'Android' }
        expect(personInitialAndUTMProperties(propertiesOsNameOnly)).toEqual({
            $os: 'Android',
            $os_name: 'Android',
            $set_once: { $initial_os: 'Android' },
            $set: { $os: 'Android' },
        })
        // Test that $os takes precedence, with $os_name preserved (although this should not happen in the wild)
        const propertiesBothOsKeys = { $os: 'Windows', $os_name: 'Android' }
        expect(personInitialAndUTMProperties(propertiesBothOsKeys)).toEqual({
            $os: 'Windows',
            $os_name: 'Android',
            $set_once: { $initial_os: 'Windows' },
            $set: { $os: 'Windows' },
        })
    })
    it('does not map server-side $os/$os_version onto the person without device context', () => {
        // posthog-python on a Linux host stamps its own $os on every event. Without device
        // evidence it must not reach $set or $set_once, or it permanently poisons $initial_os.
        const properties = {
            $lib: 'posthog-python',
            $os: 'Linux',
            $os_version: '5.15.0',
            utm_source: 'newsletter',
        }
        expect(personInitialAndUTMProperties(properties)).toEqual({
            $lib: 'posthog-python',
            $os: 'Linux',
            $os_version: '5.15.0',
            utm_source: 'newsletter',
            $set: { utm_source: 'newsletter' },
            $set_once: { $initial_utm_source: 'newsletter' },
        })
    })
    it('drops $os_version even when $os is absent (server host)', () => {
        expect(personInitialAndUTMProperties({ $os_version: '5.15.0' })).toEqual({ $os_version: '5.15.0' })
    })
    it.each([
        ['$browser present (web)', { $os: 'Linux', $browser: 'Chrome' }, 'Linux'],
        ['$device_type present (web)', { $os: 'Linux', $device_type: 'Desktop' }, 'Linux'],
        ['$os_name present (mobile)', { $os: 'iOS', $os_name: 'iOS' }, 'iOS'],
        ['no device context (server host OS)', { $os: 'Linux' }, undefined],
        ['$current_url is not device evidence', { $os: 'Linux', $current_url: 'https://x.com' }, undefined],
    ])('maps $os to $initial_os only with device context: %s', (_desc, properties, expected) => {
        const result = personInitialAndUTMProperties({ ...properties })
        const setOnce = result.$set_once as Record<string, any> | undefined
        const set = result.$set as Record<string, any> | undefined
        expect(setOnce?.$initial_os).toBe(expected)
        if (expected === undefined) {
            // server host $os must not reach current $set either, not just $set_once
            expect(set?.$os).toBeUndefined()
        }
    })
})
