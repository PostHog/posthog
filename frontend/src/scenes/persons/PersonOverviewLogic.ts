import { actions, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import type { personOverviewLogicType } from './PersonOverviewLogicType'

export interface PersonOverviewLogicProps {
    person: PersonType
}

export interface PersonOverviewStats {
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

export const personOverviewLogic = kea<personOverviewLogicType>([
    path(['scenes', 'persons', 'personOverviewLogic']),
    props({} as PersonOverviewLogicProps),
    key((props) => props.person.uuid || props.person.id || 'unknown'),

    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),

    actions(() => ({
        loadOverviewStats: true,
    })),

    loaders(({ props }) => ({
        overviewStats: [
            null as PersonOverviewStats | null,
            {
                loadOverviewStats: async () => {
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
            (_, props) => [props.person],
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
                    email: { type: 'email', priority: 1, symbol: 'email' },
                    $email: { type: 'email', priority: 1, symbol: 'email' },

                    // Name properties
                    name: { type: 'name', priority: 2, symbol: 'person' },
                    $name: { type: 'name', priority: 2, symbol: 'person' },
                    first_name: { type: 'name', priority: 3, symbol: 'person' },
                    last_name: { type: 'name', priority: 4, symbol: 'person' },

                    // Current/Latest Browser properties (preferred)
                    $browser: { type: 'browser', priority: 5 },
                    $browser_version: { type: 'browser', priority: 15 },

                    // Current/Latest OS properties (preferred)
                    $os: { type: 'os', priority: 6 },
                    // $initial_os removed - we prefer current OS only

                    // Current/Latest Location properties (preferred)
                    $geoip_country_code: { type: 'location', priority: 7 },
                    $geoip_city_name: { type: 'location', priority: 8, symbol: 'location' },
                    $geoip_time_zone: { type: 'location', priority: 9, symbol: 'clock' },
                    $geoip_continent_name: { type: 'location', priority: 18, symbol: 'globe' },

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
                    company: { type: 'demographic', priority: 23, symbol: 'building' },
                    title: { type: 'demographic', priority: 24, symbol: 'briefcase' },
                    phone: { type: 'demographic', priority: 25, symbol: 'phone' },
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

                // Get country flag symbol for current properties only (using ISO 3166-1 alpha-2 country codes)
                const getCountrySymbol = (countryCode: string): string => {
                    const countryCodeUpper = countryCode.toUpperCase()
                    const countryFlags: Record<string, string> = {
                        // A
                        AD: '🇦🇩',
                        AE: '🇦🇪',
                        AF: '🇦🇫',
                        AG: '🇦🇬',
                        AI: '🇦🇮',
                        AL: '🇦🇱',
                        AM: '🇦🇲',
                        AO: '🇦🇴',
                        AQ: '🇦🇶',
                        AR: '🇦🇷',
                        AS: '🇦🇸',
                        AT: '🇦🇹',
                        AU: '🇦🇺',
                        AW: '🇦🇼',
                        AX: '🇦🇽',
                        AZ: '🇦🇿',
                        // B
                        BA: '🇧🇦',
                        BB: '🇧🇧',
                        BD: '🇧🇩',
                        BE: '🇧🇪',
                        BF: '🇧🇫',
                        BG: '🇧🇬',
                        BH: '🇧🇭',
                        BI: '🇧🇮',
                        BJ: '🇧🇯',
                        BL: '🇧🇱',
                        BM: '🇧🇲',
                        BN: '🇧🇳',
                        BO: '🇧🇴',
                        BQ: '🇧🇶',
                        BR: '🇧🇷',
                        BS: '🇧🇸',
                        BT: '🇧🇹',
                        BV: '🇧🇻',
                        BW: '🇧🇼',
                        BY: '🇧🇾',
                        BZ: '🇧🇿',
                        // C
                        CA: '🇨🇦',
                        CC: '🇨🇨',
                        CD: '🇨🇩',
                        CF: '🇨🇫',
                        CG: '🇨🇬',
                        CH: '🇨🇭',
                        CI: '🇨🇮',
                        CK: '🇨🇰',
                        CL: '🇨🇱',
                        CM: '🇨🇲',
                        CN: '🇨🇳',
                        CO: '🇨🇴',
                        CR: '🇨🇷',
                        CU: '🇨🇺',
                        CV: '🇨🇻',
                        CW: '🇨🇼',
                        CX: '🇨🇽',
                        CY: '🇨🇾',
                        CZ: '🇨🇿',
                        // D
                        DE: '🇩🇪',
                        DJ: '🇩🇯',
                        DK: '🇩🇰',
                        DM: '🇩🇲',
                        DO: '🇩🇴',
                        DZ: '🇩🇿',
                        // E
                        EC: '🇪🇨',
                        EE: '🇪🇪',
                        EG: '🇪🇬',
                        EH: '🇪🇭',
                        ER: '🇪🇷',
                        ES: '🇪🇸',
                        ET: '🇪🇹',
                        EU: '🇪🇺',
                        // F
                        FI: '🇫🇮',
                        FJ: '🇫🇯',
                        FK: '🇫🇰',
                        FM: '🇫🇲',
                        FO: '🇫🇴',
                        FR: '🇫🇷',
                        // G
                        GA: '🇬🇦',
                        GB: '🇬🇧',
                        GD: '🇬🇩',
                        GE: '🇬🇪',
                        GF: '🇬🇫',
                        GG: '🇬🇬',
                        GH: '🇬🇭',
                        GI: '🇬🇮',
                        GL: '🇬🇱',
                        GM: '🇬🇲',
                        GN: '🇬🇳',
                        GP: '🇬🇵',
                        GQ: '🇬🇶',
                        GR: '🇬🇷',
                        GS: '🇬🇸',
                        GT: '🇬🇹',
                        GU: '🇬🇺',
                        GW: '🇬🇼',
                        GY: '🇬🇾',
                        // H
                        HK: '🇭🇰',
                        HM: '🇭🇲',
                        HN: '🇭🇳',
                        HR: '🇭🇷',
                        HT: '🇭🇹',
                        HU: '🇭🇺',
                        // I
                        ID: '🇮🇩',
                        IE: '🇮🇪',
                        IL: '🇮🇱',
                        IM: '🇮🇲',
                        IN: '🇮🇳',
                        IO: '🇮🇴',
                        IQ: '🇮🇶',
                        IR: '🇮🇷',
                        IS: '🇮🇸',
                        IT: '🇮🇹',
                        // J
                        JE: '🇯🇪',
                        JM: '🇯🇲',
                        JO: '🇯🇴',
                        JP: '🇯🇵',
                        // K
                        KE: '🇰🇪',
                        KG: '🇰🇬',
                        KH: '🇰🇭',
                        KI: '🇰🇮',
                        KM: '🇰🇲',
                        KN: '🇰🇳',
                        KP: '🇰🇵',
                        KR: '🇰🇷',
                        KW: '🇰🇼',
                        KY: '🇰🇾',
                        KZ: '🇰🇿',
                        // L
                        LA: '🇱🇦',
                        LB: '🇱🇧',
                        LC: '🇱🇨',
                        LI: '🇱🇮',
                        LK: '🇱🇰',
                        LR: '🇱🇷',
                        LS: '🇱🇸',
                        LT: '🇱🇹',
                        LU: '🇱🇺',
                        LV: '🇱🇻',
                        LY: '🇱🇾',
                        // M
                        MA: '🇲🇦',
                        MC: '🇲🇨',
                        MD: '🇲🇩',
                        ME: '🇲🇪',
                        MF: '🇲🇫',
                        MG: '🇲🇬',
                        MH: '🇲🇭',
                        MK: '🇲🇰',
                        ML: '🇲🇱',
                        MM: '🇲🇲',
                        MN: '🇲🇳',
                        MO: '🇲🇴',
                        MP: '🇲🇵',
                        MQ: '🇲🇶',
                        MR: '🇲🇷',
                        MS: '🇲🇸',
                        MT: '🇲🇹',
                        MU: '🇲🇺',
                        MV: '🇲🇻',
                        MW: '🇲🇼',
                        MX: '🇲🇽',
                        MY: '🇲🇾',
                        MZ: '🇲🇿',
                        // N
                        NA: '🇳🇦',
                        NC: '🇳🇨',
                        NE: '🇳🇪',
                        NF: '🇳🇫',
                        NG: '🇳🇬',
                        NI: '🇳🇮',
                        NL: '🇳🇱',
                        NO: '🇳🇴',
                        NP: '🇳🇵',
                        NR: '🇳🇷',
                        NU: '🇳🇺',
                        NZ: '🇳🇿',
                        // O
                        OM: '🇴🇲',
                        // P
                        PA: '🇵🇦',
                        PE: '🇵🇪',
                        PF: '🇵🇫',
                        PG: '🇵🇬',
                        PH: '🇵🇭',
                        PK: '🇵🇰',
                        PL: '🇵🇱',
                        PM: '🇵🇲',
                        PN: '🇵🇳',
                        PR: '🇵🇷',
                        PS: '🇵🇸',
                        PT: '🇵🇹',
                        PW: '🇵🇼',
                        PY: '🇵🇾',
                        // Q
                        QA: '🇶🇦',
                        // R
                        RE: '🇷🇪',
                        RO: '🇷🇴',
                        RS: '🇷🇸',
                        RU: '🇷🇺',
                        RW: '🇷🇼',
                        // S
                        SA: '🇸🇦',
                        SB: '🇸🇧',
                        SC: '🇸🇨',
                        SD: '🇸🇩',
                        SE: '🇸🇪',
                        SG: '🇸🇬',
                        SH: '🇸🇭',
                        SI: '🇸🇮',
                        SJ: '🇸🇯',
                        SK: '🇸🇰',
                        SL: '🇸🇱',
                        SM: '🇸🇲',
                        SN: '🇸🇳',
                        SO: '🇸🇴',
                        SR: '🇸🇷',
                        SS: '🇸🇸',
                        ST: '🇸🇹',
                        SV: '🇸🇻',
                        SX: '🇸🇽',
                        SY: '🇸🇾',
                        SZ: '🇸🇿',
                        // T
                        TC: '🇹🇨',
                        TD: '🇹🇩',
                        TF: '🇹🇫',
                        TG: '🇹🇬',
                        TH: '🇹🇭',
                        TJ: '🇹🇯',
                        TK: '🇹🇰',
                        TL: '🇹🇱',
                        TM: '🇹🇲',
                        TN: '🇹🇳',
                        TO: '🇹🇴',
                        TR: '🇹🇷',
                        TT: '🇹🇹',
                        TV: '🇹🇻',
                        TW: '🇹🇼',
                        TZ: '🇹🇿',
                        // U
                        UA: '🇺🇦',
                        UG: '🇺🇬',
                        UM: '🇺🇲',
                        US: '🇺🇸',
                        UY: '🇺🇾',
                        UZ: '🇺🇿',
                        // V
                        VA: '🇻🇦',
                        VC: '🇻🇨',
                        VE: '🇻🇪',
                        VG: '🇻🇬',
                        VI: '🇻🇮',
                        VN: '🇻🇳',
                        VU: '🇻🇺',
                        // W
                        WF: '🇼🇫',
                        WS: '🇼🇸',
                        // X
                        XK: '🇽🇰',
                        // Y
                        YE: '🇾🇪',
                        YT: '🇾🇹',
                        // Z
                        ZA: '🇿🇦',
                        ZM: '🇿🇲',
                        ZW: '🇿🇼',
                    }
                    return countryFlags[countryCodeUpper] || '🌍'
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

        isLoading: [(s) => [s.overviewStatsLoading], (overviewStatsLoading: boolean) => overviewStatsLoading],
    })),
])
