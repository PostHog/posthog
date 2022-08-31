import { personInitialAndUTMProperties } from '../../../src/utils/db/utils'

describe('personInitialAndUTMProperties()', () => {
    it('adds initial and utm properties', () => {
        const properties = {
            distinct_id: 2,
            $browser: 'Chrome',
            $current_url: 'https://test.com',
            $os: 'Mac OS X',
            $browser_version: '95',
            $referring_domain: 'https://google.com',
            $referrer: 'https://google.com/?q=posthog',
            utm_medium: 'twitter',
            gclid: 'GOOGLE ADS ID',
            $elements: [
                { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
            ],
        }

        expect(personInitialAndUTMProperties(properties)).toEqual({
            distinct_id: 2,
            $browser: 'Chrome',
            $current_url: 'https://test.com',
            $os: 'Mac OS X',
            $browser_version: '95',
            $referring_domain: 'https://google.com',
            $referrer: 'https://google.com/?q=posthog',
            utm_medium: 'twitter',
            gclid: 'GOOGLE ADS ID',
            $elements: [
                {
                    tag_name: 'a',
                    nth_child: 1,
                    nth_of_type: 2,
                    attr__class: 'btn btn-sm',
                },
                { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
            ],
            $set: { utm_medium: 'twitter', gclid: 'GOOGLE ADS ID' },
            $set_once: {
                $initial_browser: 'Chrome',
                $initial_current_url: 'https://test.com',
                $initial_os: 'Mac OS X',
                $initial_browser_version: '95',
                $initial_utm_medium: 'twitter',
                $initial_gclid: 'GOOGLE ADS ID',
                $initial_referring_domain: 'https://google.com',
                $initial_referrer: 'https://google.com/?q=posthog',
            },
        })
    })

    it('initial current domain regression test', () => {
        const properties = {
            $current_url: 'https://test.com',
        }

        expect(personInitialAndUTMProperties(properties)).toEqual({
            $current_url: 'https://test.com',
            $set_once: { $initial_current_url: 'https://test.com' },
        })
    })
})
