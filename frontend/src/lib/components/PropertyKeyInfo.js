import React from 'react'
import { Popover } from 'antd'

export const keyMapping = {
    event: {
        $timestamp: {
            label: 'Timestamp',
            description: 'Time the event happened.',
            examples: [new Date().toISOString()],
        },
        $browser: {
            label: 'Browser',
            description: 'Name of the browser the user has used.',
            examples: ['Chrome', 'Firefox'],
        },
        $initial_browser: {
            label: 'Initial Browser',
            description: 'Name of the browser the user first used (first-touch).',
            examples: ['Chrome', 'Firefox'],
        },
        $os: {
            label: 'OS',
            description: 'The operating system of the user.',
            examples: ['Windows', 'Mac OS X'],
        },
        $initial_os: {
            label: 'Initial OS',
            description: 'The operating system that the user first used (first-touch).',
            examples: ['Windows', 'Mac OS X'],
        },
        $current_url: {
            label: 'Current URL',
            description: 'The URL visited for this event, including all the trimings.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $initial_current_url: {
            label: 'Initial Current URL',
            description: 'The first URL the user visited, including all the trimings.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $browser_version: {
            label: 'Browser Version',
            description: 'The version of the browser that was used. Used in combination with Browser.',
            examples: ['70', '79'],
        },
        $initial_browser_version: {
            label: 'Initial Browser Version',
            description:
                'The version of the browser that the user first used (first-touch). Used in combination with Browser.',
            examples: ['70', '79'],
        },
        $screen_height: {
            label: 'Screen Height',
            description: "The height of the user's screen in pixels.",
            examples: ['2160', '1050'],
        },
        $screen_width: {
            label: 'Screen Width',
            description: "The width of the user's screen in pixels.",
            examples: ['1440', '1920'],
        },
        $lib: {
            label: 'Library',
            description: 'What library was used to send the event.',
            examples: ['web', 'posthog-ios'],
        },
        $lib_version: {
            label: 'Library Version',
            description: 'Version of the library used to send the event. Used in combination with Library.',
            examples: ['1.0.3'],
        },
        $initial_referrer: {
            label: 'Initial Referrer URL',
            description: 'URL of where the user initially came from (first-touch).',
            examples: ['https://google.com/search?q=posthog&rlz=1C...'],
        },
        $initial_referring_domain: {
            label: 'Initial Referring Domain',
            description: 'Domain of where the user initially came from (first-touch).',
            examples: ['google.com', 'facebook.com'],
        },
        $referrer: {
            label: 'Referrer URL',
            description: 'URL of where the user came from most recently (last-touch).',
            examples: ['https://google.com/search?q=posthog&rlz=1C...'],
        },
        $referring_domain: {
            label: 'Referring Domain',
            description: 'Domain of where the user came from most recently (last-touch).',
            examples: ['google.com', 'facebook.com'],
        },
        $user_id: {
            label: 'User ID',
            description: (
                <span>
                    This variable will be set to the distinct ID if you've called{' '}
                    <pre style={{ display: 'inline' }}>posthog.identify('distinct id')</pre>. If the user is anonymous,
                    it'll be empty.
                </span>
            ),
        },
        $ip: {
            label: 'IP Address',
            description: 'IP address for this user when the event was sent.',
            examples: ['203.0.113.0'],
        },
        $host: {
            label: 'Host',
            description: 'The hostname of the Current URL.',
            examples: ['example.com', 'localhost:8000'],
        },
        $pathname: {
            label: 'Path Name',
            description: 'The path of the Current URL, which means everything in the url after the domain.',
            examples: ['/pricing', '/about-us/team'],
        },
        $search_engine: {
            label: 'Search Engine',
            description: 'The search engine the user came in from (if any). This is last-touch.',
            examples: ['Google', 'DuckDuckGo'],
        },
        distinct_id: {
            label: 'Distinct ID',
            description: (
                <span>
                    Distinct ID either given by calling{' '}
                    <pre style={{ display: 'inline' }}>posthog.identify('distinct id')</pre> or generated automatically
                    if the user is anonymous.
                </span>
            ),
            examples: ['1234', '16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
        },
        $active_feature_flags: {
            label: 'Active Feature Flags',
            description: 'Keys of the feature flags that were active while this event was sent.',
            examples: ['beta-feature'],
        },
        $feature_flag_response: {
            label: 'Feature Flag Response',
            description: 'What the call to feature flag responded with.',
            examples: ['true', 'false'],
        },
        $feature_flag: {
            label: 'Feature Flag',
            description: (
                <>
                    The feature flag that was called.
                    <br />
                    <br />
                    Warning! This only works in combination with the $feature_flag_called event. If you want to filter
                    other events, try "Active Feature Flags".
                </>
            ),
            examples: ['beta-feature'],
        },
        $device: {
            label: 'Device',
            description: 'The mobile device that was used.',
            examples: ['iPad', 'iPhone', 'Android'],
        },
        $sentry_url: {
            label: 'Sentry URL',
            description: 'Direct link to the exception in Sentry',
            examples: ['https://sentry.io/...'],
        },
        $device: {
            label: 'Device',
            description: 'The mobile device that was used.',
            examples: ['iPad', 'iPhone', 'Android'],
        },

        // UTM tags
        utm_source: {
            label: 'UTM Source',
            description: 'The last UTM source tag that this user saw (last-touch).',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'The initial UTM source tag that this user saw (first-touch).',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        utm_medium: {
            label: 'UTM Medium',
            description: 'The last UTM medium tag that this user saw (last-touch).',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $initial_utm_medium: {
            label: 'Initial UTM Medium',
            description: 'The initial UTM medium tag that this user saw (first-touch).',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        utm_campaign: {
            label: 'UTM Campaign',
            description: 'The last UTM campaign tag that this user saw (last-touch).',
            examples: ['feature launch', 'discount'],
        },
        $initial_utm_campaign: {
            label: 'Initial UTM Campaign',
            description: 'The initial UTM campaign tag that this user saw (first-touch).',
            examples: ['feature launch', 'discount'],
        },
        utm_content: {
            label: 'UTM content',
            description: 'The last UTM content tag that this user saw (last-touch).',
            examples: ['bottom link', 'second button'],
        },
        $initial_utm_content: {
            label: 'Initial UTM content',
            description: 'The initial UTM content tag that this user saw (first-touch).',
            examples: ['bottom link', 'second button'],
        },
        utm_term: {
            label: 'UTM Term',
            description: 'The last UTM term tag that this user saw (last-touch).',
            examples: ['free goodies'],
        },
        $initial_utm_term: {
            label: 'Initial UTM Term',
            description: 'The initial UTM term tag that this user saw (first-touch).',
            examples: ['free goodies'],
        },

        // Hidden fields
        $had_persisted_distinct_id: {
            label: '$had_persisted_distinct_id',
            description: '',
            hide: true,
        },
        $sentry_event_id: {
            label: 'Sentry Event ID',
            description: 'This is the Sentry key for an event.',
            examples: ['byroc2ar9ee4ijqp'],
            hide: true,
        },
        $sentry_exception: {
            label: 'Sentry exception',
            description: 'Raw Sentry exception data',
            hide: true,
        },
        $ce_version: {
            label: '$ce_version',
            description: '',
            hide: true,
        },
        $anon_distinct_id: {
            label: 'Anon Distinct ID',
            description: 'If the user was previously anonymous, their anonymous ID will be set here.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            hide: true,
        },
        $event_type: {
            label: 'Event Type',
            description:
                'When the event is an $autocapture event, this specifies what the action was against the element.',
            examples: ['click', 'submit', 'change'],
        },
        $insert_id: {
            label: 'Insert ID',
            description: 'Unique insert ID for the event.',
            hide: true,
        },
        $time: {
            label: 'Time',
            description: 'Time as given by the client.',
            hide: true,
        },
        $device_id: {
            label: 'Device ID',
            description: 'Unique ID for that device, consistent even if users are logging in/out.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            hide: true,
        },
    },
    element: {
        tag_name: {
            label: 'Tag Name',
            description: (
                <span>
                    Tag name of the element you want to filter on.
                    <br />
                    <i>Note: filtering on element properties only works with $autocapture</i>
                </span>
            ),
            examples: ['a', 'button', 'input'],
        },
        selector: {
            label: 'CSS Selector',
            description: (
                <span>
                    Select any element by css selector
                    <br />
                    <i>Note: filtering on element properties only works with $autocapture</i>
                </span>
            ),
            examples: ['div > a', 'table td:nth-child(2)'],
        },
        text: {
            label: 'Text',
            description: (
                <span>
                    The inner text of the element.
                    <br />
                    <i>Note: filtering on element properties only works with $autocapture</i>
                </span>
            ),
        },
        href: {
            label: 'href',
            description: (
                <span>
                    The href attribute of the element.
                    <br />
                    <i>Note: filtering on element properties only works with $autocapture</i>
                </span>
            ),
            examples: ['https://posthog.com/about'],
        },
    },
}

export function PropertyKeyInfo({ value, type = 'event' }) {
    let data
    if (type === 'cohort') {
        return value.name
    } else {
        data = keyMapping[type][value]
    }

    if (!data) {
        return value
    }

    return (
        <Popover
            overlayStyle={{ maxWidth: 500 }}
            placement="right"
            title={
                <span>
                    <span className="property-key-info-logo" />
                    {data.label}
                </span>
            }
            content={
                <span>
                    {data.examples ? (
                        <>
                            <span>{data.description}</span>
                            <br />
                            <br />
                            <span>
                                <i>Example: </i>
                                {data.examples.join(', ')}
                            </span>
                        </>
                    ) : (
                        data.description
                    )}
                    <hr />
                    Sent as <pre style={{ display: 'inline', padding: '2px 3px' }}>{value}</pre>
                </span>
            }
        >
            <div className="property-key-info">
                <span className="property-key-info-logo" />
                {data.label}
            </div>
        </Popover>
    )
}
