import { actions, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import type { personSummaryLogicType } from './PersonSummaryLogicType'

export interface PersonSummaryLogicProps {
    person: PersonType
}

export interface PersonSummaryStats {
    sessionCount: number
    pageviewCount: number
    eventCount: number
    lastSeenAt: string | null
    firstSeenAt: string | null
}

export interface ImportantProperty {
    key: string
    value: unknown
    type: 'email' | 'name' | 'browser' | 'os' | 'location' | 'device' | 'utm' | 'url' | 'demographic' | 'custom'
    priority: number
    symbol?: string
}

export const personSummaryLogic = kea<personSummaryLogicType>([
    path(['scenes', 'persons', 'personSummaryLogic']),
    props({} as PersonSummaryLogicProps),
    key((props) => props.person.uuid || props.person.id || 'unknown'),

    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),

    actions(() => ({
        loadSummaryStats: true,
    })),

    loaders(({ props }) => ({
        summaryStats: [
            null as PersonSummaryStats | null,
            {
                loadSummaryStats: async () => {
                    if (!props.person.uuid) {
                        return null
                    }

                    // Query for session count, pageview count, total events, and activity dates
                    const statsQuery = hogql`
                        SELECT 
                            count(DISTINCT $session_id) as session_count,
                            countIf(event = '$pageview') as pageview_count,
                            count(*) as event_count,
                            min(timestamp) as first_seen,
                            max(timestamp) as last_seen
                        FROM events 
                        WHERE person_id = ${props.person.uuid}
                        AND timestamp >= now() - interval 90 day
                    `

                    const response = await api.queryHogQL(statsQuery)
                    const row = response.results?.[0]

                    if (!row) {
                        return {
                            sessionCount: 0,
                            pageviewCount: 0,
                            eventCount: 0,
                            lastSeenAt: null,
                            firstSeenAt: null,
                        }
                    }

                    return {
                        sessionCount: row[0] || 0,
                        pageviewCount: row[1] || 0,
                        eventCount: row[2] || 0,
                        firstSeenAt: row[3] || null,
                        lastSeenAt: row[4] || null,
                    }
                },
            },
        ],
    })),

    selectors(() => ({
        importantProperties: [
            (s, props) => [props.person],
            (person: PersonType): ImportantProperty[] => {
                if (!person?.properties) {
                    return []
                }

                const properties: ImportantProperty[] = []
                const props = person.properties

                // Define property priorities, types, and symbols based on PostHog documentation
                // Prefer current/latest properties except for acquisition data (UTM, landing page, referrer)
                const propertyConfig: Record<
                    string,
                    { type: ImportantProperty['type']; priority: number; symbol?: string }
                > = {
                    // Email properties (highest priority)
                    email: { type: 'email', priority: 1, symbol: '📧' },
                    $email: { type: 'email', priority: 1, symbol: '📧' },

                    // Name properties
                    name: { type: 'name', priority: 2, symbol: '👤' },
                    $name: { type: 'name', priority: 2, symbol: '👤' },
                    first_name: { type: 'name', priority: 3, symbol: '👤' },
                    last_name: { type: 'name', priority: 4, symbol: '👤' },

                    // Current/Latest Browser properties (preferred)
                    $browser: { type: 'browser', priority: 5 },
                    $browser_version: { type: 'browser', priority: 15 },

                    // Current/Latest OS properties (preferred)
                    $os: { type: 'os', priority: 6 },
                    // $initial_os removed - we prefer current OS only

                    // Current/Latest Location properties (preferred)
                    $geoip_country_name: { type: 'location', priority: 7 },
                    $geoip_city_name: { type: 'location', priority: 8, symbol: '🏙️' },
                    $geoip_time_zone: { type: 'location', priority: 9, symbol: '🕐' },
                    $geoip_continent_name: { type: 'location', priority: 18, symbol: '🌍' },

                    // Current/Latest Device properties (preferred)
                    $device_type: { type: 'device', priority: 10 },
                    // $initial_device_type removed - we prefer current device only

                    // UTM properties (acquisition data - keep initial values important)
                    utm_source: { type: 'utm', priority: 11 },
                    utm_medium: { type: 'utm', priority: 12 },
                    utm_campaign: { type: 'utm', priority: 13 },
                    utm_content: { type: 'utm', priority: 14 },

                    // URL properties (acquisition data - prefer initial/first-touch)
                    $initial_current_url: { type: 'url', priority: 17 },
                    // $initial_referrer removed - referring domain is more useful
                    $initial_referring_domain: { type: 'url', priority: 19 },

                    // Initial Location properties (acquisition context - lower priority than current)
                    $initial_geoip_country_name: { type: 'location', priority: 27 },
                    $initial_geoip_city_name: { type: 'location', priority: 28 },
                    $initial_geoip_continent_name: { type: 'location', priority: 29 },
                    $initial_geoip_time_zone: { type: 'location', priority: 31 },

                    // Demographic properties
                    company: { type: 'demographic', priority: 23, symbol: '🏢' },
                    title: { type: 'demographic', priority: 24, symbol: '💼' },
                    phone: { type: 'demographic', priority: 25, symbol: '📞' },
                }

                // Get browser symbol for current properties only
                const getBrowserSymbol = (browser: string): string => {
                    const browserLower = browser.toLowerCase()
                    if (browserLower.includes('chrome')) {
                        return 'chrome'
                    }
                    if (browserLower.includes('firefox')) {
                        return 'firefox'
                    }
                    if (browserLower.includes('safari')) {
                        return 'safari'
                    }
                    if (browserLower.includes('edge')) {
                        return 'edge'
                    }
                    if (browserLower.includes('opera')) {
                        return 'opera'
                    }
                    return 'chrome'
                }

                // Get OS symbol for current properties only
                const getOSSymbol = (os: string): string => {
                    const osLower = os.toLowerCase()
                    if (osLower.includes('mac') || osLower.includes('darwin')) {
                        return 'macos'
                    }
                    if (osLower.includes('windows')) {
                        return 'windows'
                    }
                    if (osLower.includes('linux')) {
                        return 'linux'
                    }
                    if (osLower.includes('android')) {
                        return 'android'
                    }
                    if (osLower.includes('ios')) {
                        return 'ios'
                    }
                    return 'other'
                }

                // Get country flag symbol for current properties only
                const getCountrySymbol = (country: string): string => {
                    const countryLower = country.toLowerCase()
                    const countryFlags: Record<string, string> = {
                        'united states': '🇺🇸',
                        usa: '🇺🇸',
                        us: '🇺🇸',
                        canada: '🇨🇦',
                        'united kingdom': '🇬🇧',
                        uk: '🇬🇧',
                        germany: '🇩🇪',
                        france: '🇫🇷',
                        italy: '🇮🇹',
                        spain: '🇪🇸',
                        netherlands: '🇳🇱',
                        australia: '🇦🇺',
                        japan: '🇯🇵',
                        china: '🇨🇳',
                        india: '🇮🇳',
                        brazil: '🇧🇷',
                        mexico: '🇲🇽',
                        russia: '🇷🇺',
                        'south korea': '🇰🇷',
                        singapore: '🇸🇬',
                        sweden: '🇸🇪',
                        norway: '🇳🇴',
                        denmark: '🇩🇰',
                        finland: '🇫🇮',
                        switzerland: '🇨🇭',
                        austria: '🇦🇹',
                        belgium: '🇧🇪',
                        poland: '🇵🇱',
                    }
                    return countryFlags[countryLower] || '🌍'
                }

                // Get device type symbol for current properties only
                const getDeviceSymbol = (deviceType: string): string => {
                    const deviceLower = deviceType.toLowerCase()
                    if (deviceLower.includes('mobile')) {
                        return 'mobile'
                    }
                    if (deviceLower.includes('tablet')) {
                        return 'tablet'
                    }
                    if (deviceLower.includes('desktop')) {
                        return 'desktop'
                    }
                    return 'desktop'
                }

                // Check if a property is an acquisition property (no symbols for these)
                const isAcquisitionProperty = (key: string): boolean => {
                    return key.startsWith('$initial_') || key.startsWith('utm_')
                }

                // First, add all known important properties
                Object.entries(propertyConfig).forEach(([key, config]) => {
                    if (props[key] && props[key] !== '' && props[key] !== null) {
                        let symbol = config.symbol

                        // Only add dynamic symbols for non-acquisition properties
                        if (!isAcquisitionProperty(key)) {
                            if (config.type === 'browser' && !symbol) {
                                symbol = getBrowserSymbol(String(props[key]))
                            } else if (config.type === 'os' && !symbol) {
                                symbol = getOSSymbol(String(props[key]))
                            } else if (config.type === 'location' && key.includes('country') && !symbol) {
                                symbol = getCountrySymbol(String(props[key]))
                            } else if (config.type === 'device' && !symbol) {
                                symbol = getDeviceSymbol(String(props[key]))
                            }
                        }

                        properties.push({
                            key,
                            value: props[key],
                            type: config.type,
                            priority: config.priority,
                            symbol: isAcquisitionProperty(key) ? undefined : symbol,
                        })
                    }
                })

                // Sort by priority and limit to top 10 properties
                return properties.sort((a, b) => a.priority - b.priority).slice(0, 10)
            },
        ],

        isLoading: [(s) => [s.summaryStatsLoading], (summaryStatsLoading: boolean) => summaryStatsLoading],
    })),
])
