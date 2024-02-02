import { KeyMapping, KeyMappingInterface, PropertyFilterValue } from '~/types'

import { TaxonomicFilterGroupType } from './components/TaxonomicFilter/types'
import { Link } from './lemon-ui/Link'

// If adding event properties with labels, check whether they should be added to
// PROPERTY_NAME_ALIASES in posthog/api/property_definition.py
// see code to output JSON below this
export const KEY_MAPPING: KeyMappingInterface = {
    event: {
        '': {
            label: 'All events',
            description: 'This is a wildcard that matches all events.',
        },
        $timestamp: {
            label: 'Timestamp',
            description: 'Time the event happened.',
            examples: [new Date().toISOString()],
        },
        $sent_at: {
            label: 'Sent At',
            description:
                'Time the event was sent to PostHog. Used for correcting the event timestamp when the device clock is off.',
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
        $browser_language: {
            label: 'Browser Language',
            description: 'Language.',
            examples: ['en', 'en-US', 'cn', 'pl-PL'],
        },
        $current_url: {
            label: 'Current URL',
            description: 'The URL visited at the time of the event.',
            examples: ['https://example.com/interesting-article?parameter=true'],
        },
        $initial_current_url: {
            label: 'Initial Current URL',
            description: 'The first URL the user visited.',
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
        $raw_user_agent: {
            label: 'Raw User Agent',
            description:
                'PostHog process information like browser, OS, and device type from the user agent string. This is the raw user agent string.',
            examples: ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'],
        },
        $user_agent: {
            label: 'Raw User Agent',
            description: 'Some SDKs (like Android) send the raw user agent as $user_agent.',
            examples: ['Dalvik/2.1.0 (Linux; U; Android 11; Pixel 3 Build/RQ2A.210505.002)'],
        },
        $screen_height: {
            label: 'Screen Height',
            description: "The height of the user's entire screen (in pixels).",
            examples: ['2160', '1050'],
        },
        $screen_width: {
            label: 'Screen Width',
            description: "The width of the user's entire screen (in pixels).",
            examples: ['1440', '1920'],
        },
        $screen_name: {
            label: 'Screen Name',
            description: 'The name of the active screen.',
        },
        $viewport_height: {
            label: 'Viewport Height',
            description: "The height of the user's actual browser window (in pixels).",
            examples: ['2094', '1031'],
        },
        $viewport_width: {
            label: 'Viewport Width',
            description: "The width of the user's actual browser window (in pixels).",
            examples: ['1439', '1915'],
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
        $lib_version__major: {
            label: 'Library Version (Major)',
            description: 'Major version of the library used to send the event.',
            examples: [1],
        },
        $lib_version__minor: {
            label: 'Library Version (Minor)',
            description: 'Minor version of the library used to send the event.',
            examples: [0],
        },
        $lib_version__patch: {
            label: 'Library Version (Patch)',
            description: 'Patch version of the library used to send the event.',
            examples: [3],
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
                    <pre className="inline">posthog.identify('distinct id')</pre>. If the user is anonymous, it'll be
                    empty.
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
        $active_feature_flags: {
            label: 'Active Feature Flags',
            description: 'Keys of the feature flags that were active while this event was sent.',
            examples: ["['beta-feature']"],
        },
        $enabled_feature_flags: {
            label: 'Enabled Feature Flags',
            description:
                'Keys and multivariate values of the feature flags that were active while this event was sent.',
            examples: ['{"flag": "value"}'],
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
        $survey_response: {
            label: 'Survey Response',
            description: 'The response value for the first question in the survey.',
            examples: ['I love it!', 5, "['choice 1', 'choice 3']"],
        },
        $survey_name: {
            label: 'Survey Name',
            description: 'The name of the survey.',
            examples: ['Product Feedback for New Product', 'Home page NPS'],
        },
        $survey_questions: {
            label: 'Survey Questions',
            description: 'The questions asked in the survey.',
        },
        $survey_id: {
            label: 'Survey ID',
            description: 'The unique identifier for the survey.',
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
        $device_type: {
            label: 'Device Type',
            description: 'The type of device that was used (last-touch).',
            examples: ['Mobile', 'Tablet', 'Desktop'],
        },
        $initial_device_type: {
            label: 'Initial Device Type',
            description: 'The initial type of device that was used (first-touch).',
            examples: ['Mobile', 'Tablet', 'Desktop'],
        },
        $screen_density: {
            label: 'Screen density',
            description:
                'The logical density of the display. This is a scaling factor for the Density Independent Pixel unit, where one DIP is one pixel on an approximately 160 dpi screen (for example a 240x320, 1.5"x2" screen), providing the baseline of the system\'s display. Thus on a 160dpi screen this density value will be 1; on a 120 dpi screen it would be .75; etc.',
            examples: [2.75],
        },
        $device_model: {
            label: 'Device Model',
            description: 'The model of the device that was used.',
            examples: ['iPhone9,3', 'SM-G965W'],
        },
        $network_wifi: {
            label: 'Network WiFi',
            description: 'Whether the user was on WiFi when the event was sent.',
            examples: ['true', 'false'],
        },
        $network_bluetooth: {
            label: 'Network Bluetooth',
            description: 'Whether the user was on Bluetooth when the event was sent.',
            examples: ['true', 'false'],
        },
        $network_cellular: {
            label: 'Network Cellular',
            description: 'Whether the user was on cellular when the event was sent.',
            examples: ['true', 'false'],
        },
        $pageview: {
            label: 'Pageview',
            description: 'When a user loads (or reloads) a page.',
        },
        $pageview_id: {
            label: 'Pageview ID',
            description: "PostHog's internal ID for matching events to a pageview.",
            system: true,
        },
        $pageleave: {
            label: 'Pageleave',
            description: 'When a user leaves a page.',
        },
        $autocapture: {
            label: 'Autocapture',
            description: 'User interactions that were automatically captured.',
            examples: ['clicked button'],
        },
        $autocapture_disabled_server_side: {
            label: 'Autocapture Disabled Server-Side',
            description: 'If autocapture has been disabled server-side.',
            system: true,
        },
        $console_log_recording_enabled_server_side: {
            label: 'Console Log Recording Enabled Server-Side',
            description: 'If console log recording has been enabled server-side.',
            system: true,
        },
        $session_recording_recorder_version_server_side: {
            label: 'Session Recording Recorder Version Server-Side',
            description: 'The version of the session recording recorder that is enabled server-side.',
            examples: ['v2'],
            system: true,
        },
        $screen: {
            label: 'Screen',
            description: 'When a user loads a screen in a mobile app.',
        },
        $feature_flag_called: {
            label: 'Feature Flag Called',
            description: (
                <>
                    The feature flag that was called.
                    <br />
                    <br />
                    Warning! This only works in combination with the $feature_flag event. If you want to filter other
                    events, try "Active Feature Flags".
                </>
            ),
            examples: ['beta-feature'],
        },
        $feature_flag_payloads: {
            label: 'Feature Flag Payloads',
            description: 'Feature flag payloads active in the environment.',
        },
        $feature_view: {
            label: 'Feature View',
            description: 'When a user views a feature.',
        },
        $feature_interaction: {
            label: 'Feature Interaction',
            description: 'When a user interacts with a feature.',
        },
        $capture_metrics: {
            label: 'Capture Metrics',
            description: 'Metrics captured with values pertaining to your systems at a specific point in time',
        },
        $identify: {
            label: 'Identify',
            description: 'A user has been identified with properties',
        },
        $create_alias: {
            label: 'Alias',
            description: 'An alias ID has been added to a user',
        },
        $merge_dangerously: {
            label: 'Merge',
            description: 'An alias ID has been added to a user',
        },
        $groupidentify: {
            label: 'Group Identify',
            description: 'A group has been identified with properties',
        },
        $groups: {
            label: 'Groups',
            description: 'Relevant groups',
        },
        // There are at most 5 group types per project, so indexes 0, 1, 2, 3, and 4
        $group_0: {
            label: 'Group 1',
            system: true,
        },
        $group_1: {
            label: 'Group 2',
            system: true,
        },
        $group_2: {
            label: 'Group 3',
            system: true,
        },
        $group_3: {
            label: 'Group 4',
            system: true,
        },
        $group_4: {
            label: 'Group 5',
            system: true,
        },
        $group_set: {
            label: 'Group Set',
            description: 'Group properties to be set',
        },
        $group_key: {
            label: 'Group Key',
            description: 'Specified group key',
        },
        $group_type: {
            label: 'Group Type',
            description: 'Specified group type',
        },
        $window_id: {
            label: 'Window ID',
            description: 'Unique window ID for session recording disambiguation',
            system: true,
        },
        $session_id: {
            label: 'Session ID',
            description: 'Unique session ID for session recording disambiguation',
            system: true,
        },
        $rageclick: {
            label: 'Rageclick',
            description: 'A user has rapidly and repeatedly clicked in a single place',
        },
        $set: {
            label: 'Set',
            description: 'Person properties to be set',
        },
        $set_once: {
            label: 'Set Once',
            description: 'Person properties to be set if not set already (i.e. first-touch)',
        },
        $capture_failed_request: {
            label: 'Capture Failed Request',
            description: '',
        },
        $plugins_succeeded: {
            label: 'Plugins Succeeded',
            description: (
                <>
                    Plugins that successfully processed the event, e.g. edited properties (plugin method{' '}
                    <code>processEvent</code>).
                </>
            ),
        },
        $plugins_failed: {
            label: 'Plugins Failed',
            description: (
                <>
                    Plugins that failed to process the event (plugin method <code>processEvent</code>).
                </>
            ),
        },
        $plugins_deferred: {
            label: 'Plugins Deferred',
            description: (
                <>
                    Plugins to which the event was handed off post-ingestion, e.g. for export (plugin method{' '}
                    <code>onEvent</code>).
                </>
            ),
        },
        $$plugin_metrics: {
            label: 'Plugin Metric',
            description: 'Performance metrics for a given plugin.',
        },
        $creator_event_uuid: {
            label: 'Creator Event ID',
            description: 'Unique ID for the event, which created this person.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
        },

        // UTM tags
        utm_source: {
            label: 'UTM Source',
            description: 'UTM source tag (last-touch).',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'UTM source tag (first-touch).',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        utm_medium: {
            label: 'UTM Medium',
            description: 'UTM medium tag (last-touch).',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $initial_utm_medium: {
            label: 'Initial UTM Medium',
            description: 'UTM medium tag (first-touch).',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        utm_campaign: {
            label: 'UTM Campaign',
            description: 'UTM campaign tag (last-touch).',
            examples: ['feature launch', 'discount'],
        },
        utm_name: {
            label: 'UTM Name',
            description: 'UTM campaign tag, sent via Segment (last-touch).',
            examples: ['feature launch', 'discount'],
        },
        $initial_utm_name: {
            label: 'Initial UTM Name',
            description: 'UTM campaign tag, sent via Segment (first-touch).',
            examples: ['feature launch', 'discount'],
        },
        $initial_utm_campaign: {
            label: 'Initial UTM Campaign',
            description: 'UTM campaign tag (first-touch).',
            examples: ['feature launch', 'discount'],
        },
        utm_content: {
            label: 'UTM Content',
            description: 'UTM content tag (last-touch).',
            examples: ['bottom link', 'second button'],
        },
        $initial_utm_content: {
            label: 'Initial UTM Content',
            description: 'UTM content tag (first-touch).',
            examples: ['bottom link', 'second button'],
        },
        utm_term: {
            label: 'UTM Term',
            description: 'UTM term tag (last-touch).',
            examples: ['free goodies'],
        },
        $initial_utm_term: {
            label: 'Initial UTM Term',
            description: 'UTM term tag (first-touch).',
            examples: ['free goodies'],
        },
        $performance_page_loaded: {
            label: 'Page Loaded',
            description: "The time taken until the browser's page load event in milliseconds.",
        },
        $performance_raw: {
            label: 'Browser Performance',
            description:
                'The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired',
            system: true,
        },
        $had_persisted_distinct_id: {
            label: '$had_persisted_distinct_id',
            description: '',
            system: true,
        },
        $sentry_event_id: {
            label: 'Sentry Event ID',
            description: 'This is the Sentry key for an event.',
            examples: ['byroc2ar9ee4ijqp'],
            system: true,
        },
        $sentry_exception: {
            label: 'Sentry exception',
            description: 'Raw Sentry exception data',
            system: true,
        },
        $sentry_exception_message: {
            label: 'Sentry exception message',
        },
        $sentry_exception_type: {
            label: 'Sentry exception type',
            description: 'Class name of the exception object',
        },
        $sentry_tags: {
            label: 'Sentry tags',
            description: 'Tags sent to Sentry along with the exception',
        },
        $exception_type: {
            label: 'Exception type',
            description: 'Exception categorized into types. E.g. "Error"',
        },
        $exception_message: {
            label: 'Exception Message',
            description: 'The message detected on the error.',
        },
        $exception_source: {
            label: 'Exception source',
            description: 'The source of the exception. E.g. JS file.',
        },
        $exception_lineno: {
            label: 'Exception source line number',
            description: 'Which line in the exception source that caused the exception.',
        },
        $exception_colno: {
            label: 'Exception source column number',
            description: 'Which column of the line in the exception source that caused the exception.',
        },
        $exception_DOMException_code: {
            label: 'DOMException code',
            description: 'If a DOMException was thrown, it also has a DOMException code.',
        },
        $exception_is_synthetic: {
            label: 'Exception is synthetic',
            description: 'Whether this was detected as a synthetic exception',
        },
        $exception_stack_trace_raw: {
            label: 'Exception raw stack trace',
            description: "The exception's stack trace, as a string.",
        },
        $exception_handled: {
            label: 'Exception was handled',
            description: 'Whether this was a handled or unhandled exception',
        },
        $exception_personURL: {
            label: 'Exception person URL',
            description: 'The PostHog person that experienced the exception',
        },
        $ce_version: {
            label: '$ce_version',
            description: '',
            system: true,
        },
        $anon_distinct_id: {
            label: 'Anon Distinct ID',
            description: 'If the user was previously anonymous, their anonymous ID will be set here.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            system: true,
        },
        distinct_id: {
            label: 'Distinct ID',
            description: 'The current distinct ID of the user',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
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
            system: true,
        },
        $time: {
            label: '$time (deprecated)',
            description:
                'Use the HogQL field `timestamp` instead. This field was previously set on some client side events.',
            system: true,
            examples: ['1681211521.345'],
        },
        $device_id: {
            label: 'Device ID',
            description: 'Unique ID for that device, consistent even if users are logging in/out.',
            examples: ['16ff262c4301e5-0aa346c03894bc-39667c0e-1aeaa0-16ff262c431767'],
            system: true,
        },
        // GeoIP
        $geoip_city_name: {
            label: 'City Name',
            description: `Name of the city matched to this event's IP address.`,
            examples: ['Sydney', 'Chennai', 'Brooklyn'],
        },
        $geoip_country_name: {
            label: 'Country Name',
            description: `Name of the country matched to this event's IP address.`,
            examples: ['Australia', 'India', 'United States'],
        },
        $geoip_country_code: {
            label: 'Country Code',
            description: `Code of the country matched to this event's IP address.`,
            examples: ['AU', 'IN', 'US'],
        },
        $geoip_continent_name: {
            label: 'Continent Name',
            description: `Name of the continent matched to this event's IP address.`,
            examples: ['Oceania', 'Asia', 'North America'],
        },
        $geoip_continent_code: {
            label: 'Continent Code',
            description: `Code of the continent matched to this event's IP address.`,
            examples: ['OC', 'AS', ' NA'],
        },
        $geoip_postal_code: {
            label: 'Postal Code',
            description: `Approximated postal code matched to this event's IP address.`,
            examples: ['2000', '600004', '11211'],
        },
        $geoip_latitude: {
            label: 'Latitude',
            description: `Approximated latitude matched to this event's IP address.`,
            examples: ['-33.8591', '13.1337', '40.7'],
        },
        $geoip_longitude: {
            label: 'Longitude',
            description: `Approximated longitude matched to this event's IP address.`,
            examples: ['151.2', '80.8008', '-73.9'],
        },
        $geoip_time_zone: {
            label: 'Timezone',
            description: `Timezone matched to this event's IP address.`,
            examples: ['Australia/Sydney', 'Asia/Kolkata', 'America/New_York'],
        },
        $geoip_subdivision_1_name: {
            label: 'Subdivision 1 Name',
            description: `Name of the subdivision matched to this event's IP address.`,
            examples: ['New South Wales', 'Tamil Nadu', 'New York'],
        },
        $geoip_subdivision_1_code: {
            label: 'Subdivision 1 Code',
            description: `Code of the subdivision matched to this event's IP address.`,
            examples: ['NSW', 'TN', 'NY'],
        },
        $geoip_subdivision_2_name: {
            label: 'Subdivision 2 Name',
            description: `Name of the second subdivision matched to this event's IP address.`,
        },
        $geoip_subdivision_2_code: {
            label: 'Subdivision 2 Code',
            description: `Code of the second subdivision matched to this event's IP address.`,
        },
        $geoip_subdivision_3_name: {
            label: 'Subdivision 3 Name',
            description: `Name of the third subdivision matched to this event's IP address.`,
        },
        $geoip_subdivision_3_code: {
            label: 'Subdivision 3 Code',
            description: `Code of the third subdivision matched to this event's IP address.`,
        },
        $geoip_disable: {
            label: 'GeoIP Disabled',
            description: `Whether to skip GeoIP processing for the event.`,
        },
        $el_text: {
            label: 'Element Text',
            description: `The text of the element that was clicked. Only sent with Autocapture events.`,
            examples: ['Click here!'],
        },
        // NOTE: This is a hack. $session_duration is a session property, not an event property
        // but we don't do a good job of tracking property types, so making it a session property
        // would require a large refactor, and this works (because all properties are treated as
        // event properties if they're not elements)
        $session_duration: {
            label: 'Session duration',
            description: (
                <span>
                    The duration of the session being tracked. Learn more about how PostHog tracks sessions in{' '}
                    <Link to="https://posthog.com/docs/user-guides/sessions">our documentation.</Link>
                    <br /> <br />
                    Note, if the duration is formatted as a single number (not 'HH:MM:SS'), it's in seconds.
                </span>
            ),
            examples: ['01:04:12'],
        },
        $app_build: {
            label: 'App Build',
            description: 'The build number for the app.',
        },
        $app_name: {
            label: 'App Name',
            description: 'The name of the app.',
        },
        $app_namespace: {
            label: 'App Namespace',
            description: 'The namespace of the app as identified in the app store.',
            examples: ['com.posthog.app'],
        },
        $app_version: {
            label: 'App Version',
            description: 'The version of the app.',
        },
        $device_manufacturer: {
            label: 'Device Manufacturer',
            description: 'The manufacturer of the device',
            examples: ['Apple', 'Samsung'],
        },
        $device_name: {
            label: 'Device Name',
            description: 'Name of the device',
            examples: ['iPhone 12 Pro', 'Samsung Galaxy 10'],
        },
        $locale: {
            label: 'Locale',
            description: 'The locale of the device',
            examples: ['en-US', 'de-DE'],
        },
        $os_name: {
            label: 'OS Name',
            description: 'The Operating System name',
            examples: ['iOS', 'Android'],
        },
        $os_version: {
            label: 'OS Version',
            description: 'The Operating System version.',
            examples: ['15.5'],
        },
        $timezone: {
            label: 'Timezone',
            description: 'The timezone as reported by the device',
        },

        $touch_x: {
            label: 'Touch X',
            description: 'The location of a Touch event on the X axis',
        },
        $touch_y: {
            label: 'Touch Y',
            description: 'The location of a Touch event on the Y axis',
        },
        $exception: {
            label: 'Exception',
            description: 'Automatically captured exceptions from the client Sentry integration',
        },
        $client_session_initial_referring_host: {
            label: 'Referrer Host',
            description: 'Host that the user came from. (First-touch, session-scoped)',
            examples: ['google.com', 'facebook.com'],
        },
        $client_session_initial_pathname: {
            label: 'Initial Path',
            description: 'Path that the user started their session on. (First-touch, session-scoped)',
            examples: ['/register', '/some/landing/page'],
        },
        $client_session_initial_utm_source: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['Google', 'Bing', 'Twitter', 'Facebook'],
        },
        $client_session_initial_utm_campaign: {
            label: 'Initial UTM Campaign',
            description: 'UTM Campaign. (First-touch, session-scoped)',
            examples: ['feature launch', 'discount'],
        },
        $client_session_initial_utm_medium: {
            label: 'Initial UTM Medium',
            description: 'UTM Medium. (First-touch, session-scoped)',
            examples: ['Social', 'Organic', 'Paid', 'Email'],
        },
        $client_session_initial_utm_content: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['bottom link', 'second button'],
        },
        $client_session_initial_utm_term: {
            label: 'Initial UTM Source',
            description: 'UTM Source. (First-touch, session-scoped)',
            examples: ['free goodies'],
        },
        // Mobile SDKs events
        'Application Opened': {
            label: 'Application Opened',
            description: 'When a user opens the app either for the first time or from the foreground.',
        },
        'Application Backgrounded': {
            label: 'Application Backgrounded',
            description: 'When a user puts the app in the background.',
        },
        'Application Updated': {
            label: 'Application Updated',
            description: 'When a user upgrades the app.',
        },
        'Application Installed': {
            label: 'Application Installed',
            description: 'When a user installs the app.',
        },
        'Application Became Active': {
            label: 'Application Became Active',
            description: 'When a user puts the app in the foreground.',
        },
        'Deep Link Opened': {
            label: 'Deep Link Opened',
            description: 'When a user opens the app via a deep link.',
        },
        $network_carrier: {
            label: 'Network Carrier',
            description: 'The network carrier that the user is on.',
            examples: ['cricket', 'telecom'],
        },
        // set by the Application Opened event
        from_background: {
            label: 'From Background',
            description: 'Whether the app was opened for the first time or from the background.',
            examples: ['true', 'false'],
        },
        // set by the Application Opened/Deep Link Opened event
        url: {
            label: 'URL',
            description: 'The deep link URL that the app was opened from.',
            examples: ['https://open.my.app'],
        },
        referring_application: {
            label: 'Referrer Application',
            description: 'The namespace of the app that made the request.',
            examples: ['com.posthog.app'],
        },
        // set by the Application Installed/Application Updated/Application Opened events
        // similar to $app_version
        version: {
            label: 'App Version',
            description: 'The version of the app',
            examples: ['1.0.0'],
        },
        previous_version: {
            label: 'App Previous Version',
            description: 'The previous version of the app',
            examples: ['1.0.0'],
        },
        // similar to $app_build
        build: {
            label: 'App Build',
            description: 'The build number for the app',
            examples: ['1'],
        },
        previous_build: {
            label: 'App Previous Build',
            description: 'The previous build number for the app',
            examples: ['1'],
        },
    },
    element: {
        tag_name: {
            label: 'Tag Name',
            description: 'HTML tag name of the element which you want to filter.',
            examples: ['a', 'button', 'input'],
        },
        selector: {
            label: 'CSS Selector',
            description: 'Select any element by CSS selector.',
            examples: ['div > a', 'table td:nth-child(2)', '.my-class'],
        },
        text: {
            label: 'Text',
            description: 'Filter on the inner text of the HTML element.',
        },
        href: {
            label: 'Target (href)',
            description: (
                <span>
                    Filter on the <code>href</code> attribute of the element.
                </span>
            ),
            examples: ['https://posthog.com/about'],
        },
    },
}

export const keyMappingKeys = Object.keys(KEY_MAPPING.event)

export function isPostHogProp(key: string): boolean {
    /*
    Returns whether a given property is a PostHog-defined property. If the property is custom-defined,
        function will return false.
    */
    if (Object.keys(KEY_MAPPING.event).includes(key) || Object.keys(KEY_MAPPING.element).includes(key)) {
        return true
    }
    return false
}

export type PropertyKey = string | null | undefined
export type PropertyType = 'event' | 'element'

// copy from https://github.com/PostHog/posthog/blob/29ac8d6b2ba5de4b65a148136b681b8e52e20429/plugin-server/src/utils/db/utils.ts#L44
const eventToPersonProperties = new Set([
    // mobile params
    '$app_build',
    '$app_name',
    '$app_namespace',
    '$app_version',
    // web params
    '$browser',
    '$browser_version',
    '$device_type',
    '$current_url',
    '$pathname',
    '$os',
    '$os_version',
    '$referring_domain',
    '$referrer',
    // campaign params - automatically added by posthog-js here https://github.com/PostHog/posthog-js/blob/master/src/utils/event-utils.ts
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_name',
    'utm_term',
    'gclid',
    'gad_source',
    'gbraid',
    'wbraid',
    'fbclid',
    'msclkid',
])

export function getKeyMapping(
    value: string | PropertyFilterValue | undefined,
    type: 'event' | 'element',
    filterGroupType?: TaxonomicFilterGroupType
): KeyMapping | null {
    if (value == undefined) {
        return null
    }

    value = value.toString()
    let data = null
    if (value in KEY_MAPPING[type]) {
        return { ...KEY_MAPPING[type][value] }
    } else if (value.startsWith('$initial_') && value.replace(/^\$initial_/, '$') in KEY_MAPPING[type]) {
        data = { ...KEY_MAPPING[type][value.replace(/^\$initial_/, '$')] }
        if (data.description) {
            data.label = `Initial ${data.label}`
            data.description = `${String(data.description)} Data from the first time this user was seen.`
        }
        return data
    } else if (filterGroupType === TaxonomicFilterGroupType.PersonProperties && value in eventToPersonProperties) {
        data = { ...KEY_MAPPING[type][value] }
        if (data.description) {
            data.label = `Latest ${data.label}`
            data.description = `${String(data.description)} Data from the latest time this user was seen.`
        }
        return data
    } else if (value.startsWith('$survey_responded/')) {
        const surveyId = value.replace(/^\$survey_responded\//, '')
        if (surveyId) {
            return {
                label: `Survey Responded: ${surveyId}`,
                description: `Whether the user responded to survey with ID: "${surveyId}".`,
            }
        }
    } else if (value.startsWith('$survey_dismissed/')) {
        const surveyId = value.replace(/^\$survey_dismissed\//, '')
        if (surveyId) {
            return {
                label: `Survey Dismissed: ${surveyId}`,
                description: `Whether the user dismissed survey with ID: "${surveyId}".`,
            }
        }
    } else if (value.startsWith('$survey_response_')) {
        const surveyIndex = value.replace(/^\$survey_response_/, '')
        if (surveyIndex) {
            const index = Number(surveyIndex) + 1
            // yes this will return 21th, but I'm applying the domain logic of
            // it being very unlikely that someone will have more than 20 questions,
            // rather than hyper optimising the suffix.
            const suffix = index === 1 ? 'st' : index === 2 ? 'nd' : index === 3 ? 'rd' : 'th'
            return {
                label: `Survey Response Question ID: ${surveyIndex}`,
                description: `The response value for the ${index}${suffix} question in the survey.`,
            }
        }
    } else if (value.startsWith('$feature/')) {
        const featureFlagKey = value.replace(/^\$feature\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature: ${featureFlagKey}`,
                description: `Value for the feature flag "${featureFlagKey}" when this event was sent.`,
                examples: ['true', 'variant-1a'],
            }
        }
    } else if (value.startsWith('$feature_enrollment/')) {
        const featureFlagKey = value.replace(/^\$feature_enrollment\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature Enrollment: ${featureFlagKey}`,
                description: `Whether the user has opted into the "${featureFlagKey}" beta program.`,
                examples: ['true', 'false'],
            }
        }
    } else if (value.startsWith('$feature_interaction/')) {
        const featureFlagKey = value.replace(/^\$feature_interaction\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature Interaction: ${featureFlagKey}`,
                description: `Whether the user has interacted with "${featureFlagKey}".`,
                examples: ['true', 'false'],
            }
        }
    }
    return null
}

export function getPropertyLabel(value: PropertyKey, type: PropertyType = 'event'): string {
    const data = getKeyMapping(value, type)
    return (data ? data.label : value)?.trim() ?? '(empty string)'
}
