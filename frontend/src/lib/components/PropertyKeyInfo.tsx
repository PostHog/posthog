import './PropertyKeyInfo.scss'
import React from 'react'
import { Popover, Typography } from 'antd'
import { KeyMapping, PropertyDefinition, PropertyFilterValue } from '~/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { TooltipPlacement } from 'antd/lib/tooltip'

export interface KeyMappingInterface {
    event: Record<string, KeyMapping>
    element: Record<string, KeyMapping>
}

export const keyMapping: KeyMappingInterface = {
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
            description: "The height of the user's entire screen (in pixels).",
            examples: ['2160', '1050'],
        },
        $screen_width: {
            label: 'Screen Width',
            description: "The width of the user's entire screen (in pixels).",
            examples: ['1440', '1920'],
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
        $enabled_feature_flags: {
            label: 'Enabled Feature Flags',
            description: 'Object of the feature flags that were active while this event was sent.',
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
        $pageview: {
            label: 'Pageview',
            description: 'When a user loads (or reloads) a page.',
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
        $capture_metrics: {
            label: 'Capture Metrics',
            description: 'Metrics captured with values pertaining to your systems at a specific point in time',
        },
        $identify: {
            label: 'Identify',
            description: 'A user has been identified with properties',
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
            hide: true,
        },
        $group_1: {
            label: 'Group 2',
            hide: true,
        },
        $group_2: {
            label: 'Group 3',
            hide: true,
        },
        $group_3: {
            label: 'Group 4',
            hide: true,
        },
        $group_4: {
            label: 'Group 5',
            hide: true,
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
            hide: true,
        },
        $session_id: {
            label: 'Session ID',
            description: 'Unique session ID for session recording disambiguation',
            hide: true,
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

        // Hidden fields
        $performance_raw: {
            label: 'Browser Performance',
            description:
                'The browser performance entries for navigation (the page), paint, and resources. That were available when the page view event fired',
            hide: true,
        },
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
        // NOTE: This is a hack. $session_duration is a session property, not an event property
        // but we don't do a good job of tracking property types, so making it a session property
        // would require a large refactor, and this works (because all properties are treated as
        // event properties if they're not elements)
        $session_duration: {
            label: 'Session duration',
            description: (
                <span>
                    The duration of the session being tracked. Learn more about how PostHog tracks sessions in{' '}
                    <a href="https://posthog.com/docs/user-guides/sessions">our documentation.</a>
                    <br /> <br />
                    Note, if the duration is formatted as a single number (not 'HH:MM:SS'), it's in seconds.
                </span>
            ),
            examples: ['01:04:12'],
        },
        $app_build: {
            label: 'App Build',
            description: 'The build number for the app',
        },
        $app_name: {
            label: 'App Name',
            description: 'The name of the app',
        },
        $app_namespace: {
            label: 'App Namespace',
            description: 'The namespace of the app as identified in the app store',
            examples: ['com.posthog.app'],
        },
        $app_version: {
            label: 'App Version',
            description: 'The version of the app',
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
            description: 'The Operating System version',
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

export const keyMappingKeys = Object.keys(keyMapping.event)

export function isPostHogProp(key: string): boolean {
    /*
    Returns whether a given property is a PostHog-defined property. If the property is custom-defined, 
        function will return false.
    */
    if (Object.keys(keyMapping.event).includes(key) || Object.keys(keyMapping.element).includes(key)) {
        return true
    }
    return false
}

interface PropertyKeyInfoInterface {
    value: string
    type?: 'event' | 'element'
    style?: React.CSSProperties
    tooltipPlacement?: TooltipPlacement
    disablePopover?: boolean
    disableIcon?: boolean
    ellipsis?: boolean
    className?: string
}

export function PropertyKeyTitle({ data }: { data: KeyMapping }): JSX.Element {
    return (
        <span>
            <span className="property-key-info-logo" />
            {data.label}
        </span>
    )
}

export function PropertyKeyDescription({
    data,
    value,
    propertyType,
}: {
    data: KeyMapping
    value: string
    propertyType?: PropertyDefinition['property_type'] | null
}): JSX.Element {
    return (
        <span>
            {data.description ? <p>{data.description}</p> : null}
            {data.examples ? (
                <p>
                    <i>Example: </i>
                    {data.examples.join(', ')}
                </p>
            ) : null}
            {data.description || data.examples ? <hr /> : null}
            <div>
                <span>
                    Sent as <code className="p-1">{value}</code>
                </span>
                <span>{propertyType && <div className="property-value-type">{propertyType}</div>}</span>
            </div>
        </span>
    )
}

export function getKeyMapping(
    value: string | PropertyFilterValue | undefined,
    type: 'event' | 'element'
): KeyMapping | null {
    if (!value) {
        return null
    }

    value = `${value}` // convert to string
    let data = null
    if (value in keyMapping[type]) {
        return { ...keyMapping[type][value] }
    } else if (value.startsWith('$initial_') && value.replace(/^\$initial_/, '$') in keyMapping[type]) {
        data = { ...keyMapping[type][value.replace(/^\$initial_/, '$')] }
        if (data.description) {
            data.label = `Initial ${data.label}`
            data.description = `${data.description} Data from the first time this user was seen.`
        }
        return data
    } else if (value.startsWith('$feature/')) {
        const featureFlagKey = value.replace(/^\$feature\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature: ${featureFlagKey}`,
                description: `Value for the feature flag "${featureFlagKey}" when this event was sent.`,
                examples: ['true', 'variant-1a'],
            }
        }
    }
    return null
}

export function getPropertyLabel(
    value: PropertyKeyInfoInterface['value'],
    type: PropertyKeyInfoInterface['type'] = 'event'
): string {
    const data = getKeyMapping(value, type)
    return (data ? data.label : value)?.trim() ?? '(empty string)'
}

export function PropertyKeyInfo({
    value,
    type = 'event',
    style,
    tooltipPlacement = undefined,
    disablePopover = false,
    disableIcon = false,
    ellipsis = true,
    className = '',
}: PropertyKeyInfoInterface): JSX.Element {
    value = `${value}` // convert to string

    const data = getKeyMapping(value, type)
    const baseValue = (data ? data.label : value)?.trim() ?? ''
    const baseValueNode = baseValue === '' ? <i>(empty string)</i> : baseValue

    // By this point, property is a PH defined property
    const innerContent = (
        <span className="property-key-info">
            {!disableIcon && !!data && <span className="property-key-info-logo" />}
            <Typography.Text
                ellipsis={ellipsis}
                style={{
                    color: 'inherit',
                    maxWidth: 400,
                    display: 'inline', // NOTE: This important and stops the whole thing from only showing "..."
                    ...style,
                }}
                title={baseValue}
                className={className}
            >
                {baseValueNode}
            </Typography.Text>
        </span>
    )

    if (!data || disablePopover) {
        return innerContent
    }

    const popoverProps = tooltipPlacement
        ? {
              visible: true,
              placement: tooltipPlacement,
          }
        : {
              align: ANTD_TOOLTIP_PLACEMENTS.horizontalPreferRight,
          }

    const popoverTitle = <PropertyKeyTitle data={data} />
    const popoverContent = <PropertyKeyDescription data={data} value={value} />

    return (
        <Popover
            overlayStyle={{ zIndex: 99999 }}
            overlayClassName={`property-key-info-tooltip ${className || ''}`}
            title={popoverTitle}
            content={popoverContent}
            {...popoverProps}
        >
            {innerContent}
        </Popover>
    )
}
