import React from 'react'
import { Popover } from 'antd'

export const keyMapping = {
    $browser: {
        label: 'Browser',
        description: 'Name of the browser the user has used.',
        examples: ['Chrome', 'Firefox'],
    },
    $os: {
        label: 'OS',
        description: 'The operating system of the user.',
        examples: ['Windows', 'Mac OS X'],
    },
    $current_url: {
        label: 'Current URL',
        description: 'The URL visited for this path, including all the trimings.',
        examples: ['https://example.com/interesting-article?parameter=true'],
    },
    $browser_version: {
        label: 'Browser Version',
        description: 'The version of the browser that was used. Used in combination with Browser.',
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
                <pre style={{ display: 'inline' }}>posthog.identify('distinct id')</pre> or generated automatically if
                the user is anonymous.
            </span>
        ),
        examples: ['1234', '16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
    },
    // Events we maybe hide entirely from the list
    $had_persisted_distinct_id: {
        label: '$had_persisted_distinct_id',
        description: '',
    },
    $device: {
        label: 'Device',
        description: 'The mobile device that was used.',
        examples: ['iPad', 'iPhone', 'Android'],
    },
    $ce_version: {
        label: '$ce_version',
        description: '',
    },
    $anon_distinct_id: {
        label: 'Anon Distinct ID',
        description: 'If the user ',
    },
    $event_type: {
        label: 'Event Type',
        description: 'When the event is an $autocapture event, this specifies what the action was against the element.',
        examples: ['click', 'submit', 'change'],
    },
    $insert_id: {
        label: 'Insert ID',
        description: 'Unique insert ID for the event.',
    },
    $time: {
        label: 'Time',
        description: 'Time as given by the client.',
    },
    $device_id: {
        label: 'Device ID',
        description: 'Unique ID for that device, consistent even if users are logging in/out.',
        examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
    },
}

export function PropertyKeyInfo({ value }) {
    let data = keyMapping[value]
    if (!data) return value
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
                    {data.description}
                    {data.examples && (
                        <span>
                            <br />
                            <br />
                            <i>Example: </i>
                            {data.examples.join(', ')}
                        </span>
                    )}
                </span>
            }
        >
            <div style={{ width: '100%' }}>
                <span className="property-key-info-logo" />
                {data.label}
            </div>
        </Popover>
    )
}
