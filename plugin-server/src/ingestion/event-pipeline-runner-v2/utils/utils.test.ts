import { personInitialAndUTMProperties, safeClickhouseString } from './utils'

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
            $set: {
                $browser_version: 'manually $set value wins',
            },
            $set_once: {
                $initial_os_version: 'manually $set_once value wins',
            },
        }

        expect(personInitialAndUTMProperties(properties)).toMatchInlineSnapshot(`
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
        `)
    })

    it('initial current domain regression test', () => {
        const properties = {
            $current_url: 'https://test.com',
        }

        expect(personInitialAndUTMProperties(properties)).toEqual({
            $current_url: 'https://test.com',
            $set_once: { $initial_current_url: 'https://test.com' },
            $set: { $current_url: 'https://test.com' },
        })
    })

    it('treats $os_name as fallback for $os', () => {
        const propertiesOsNameOnly = {
            $os_name: 'Android',
        }
        expect(personInitialAndUTMProperties(propertiesOsNameOnly)).toEqual({
            $os: 'Android',
            $os_name: 'Android',
            $set_once: { $initial_os: 'Android' },
            $set: { $os: 'Android' },
        })

        // Also test that $os takes precedence, with $os_name preserved (although this should not happen in the wild)
        const propertiesBothOsKeys = {
            $os: 'Windows',
            $os_name: 'Android',
        }
        expect(personInitialAndUTMProperties(propertiesBothOsKeys)).toEqual({
            $os: 'Windows',
            $os_name: 'Android',
            $set_once: { $initial_os: 'Windows' },
            $set: { $os: 'Windows' },
        })
    })
})

describe('safeClickhouseString', () => {
    // includes real data
    const validStrings = [
        `$autocapture`,
        `correlation analyzed`,
        `docs_search_used`,
        `$$plugin_metrics`,
        `996f3e2f-830b-42f0-b2b8-df42bb7f7144`,
        `some?819)389**^371=2++211!!@==-''''..,,weird___id`,
        `form.form-signin:attr__action="/signup"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
        `a:attr__href="/signup"href="/signup"nth-child="1"nth-of-type="1"text="Create one here.";p:nth-child="8"nth-of-type="1";form.form-signin:attr__action="/login"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
        `input:nth-child="7"nth-of-type="3";form.form-signin:attr__action="/signup"attr__class="form-signin"attr__method="post"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
        `a.nav-link:attr__class="nav-link"attr__href="/actions"href="/actions"nth-child="1"nth-of-type="1"text="Actions";li:nth-child="2"nth-of-type="2";ul.flex-sm-column.nav:attr__class="nav flex-sm-column"nth-child="1"nth-of-type="1";div.bg-light.col-md-2.col-sm-3.flex-shrink-1.pt-3.sidebar:attr__class="col-sm-3 col-md-2 sidebar flex-shrink-1 bg-light pt-3"attr__style="min-height: 100vh;"nth-child="1"nth-of-type="1";div.flex-column.flex-fill.flex-sm-row.row:attr__class="row flex-fill flex-column flex-sm-row"nth-child="1"nth-of-type="1";div.container-fluid.d-flex.flex-grow-1:attr__class="container-fluid flex-grow-1 d-flex"nth-child="1"nth-of-type="1";div:attr__id="root"attr_id="root"nth-child="1"nth-of-type="1";body:nth-child="2"nth-of-type="1"`,
    ]

    test('does not modify valid strings', () => {
        for (const str of validStrings) {
            expect(safeClickhouseString(str)).toEqual(str)
        }
    })

    test('handles surrogate unicode characters correctly', () => {
        expect(safeClickhouseString(`foo \ud83d\ bar`)).toEqual(`foo \\ud83d\\ bar`)
        expect(safeClickhouseString(`\ud83d\ bar`)).toEqual(`\\ud83d\\ bar`)
        expect(safeClickhouseString(`\ud800\ \ud803\ `)).toEqual(`\\ud800\\ \\ud803\\ `)
    })

    test('does not modify non-surrogate unicode characters', () => {
        expect(safeClickhouseString(`✨`)).toEqual(`✨`)
        expect(safeClickhouseString(`foo \u2728\ bar`)).toEqual(`foo \u2728\ bar`)
        expect(safeClickhouseString(`💜 \u1f49c\ 💜`)).toEqual(`💜 \u1f49c\ 💜`)
    })
})
