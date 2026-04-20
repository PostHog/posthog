import { processEvent } from '.'

const demoEvents = [
    {
        event: '$pageview',
        properties: {
            $os: 'Linux',
            $browser: 'Safari',
            $device_type: 'Desktop',
            $current_url: 'https://office.getjoan.com/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
            $host: 'office.getjoan.com',
            $pathname: '/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
            $browser_version: 16,
            $screen_height: 1080,
            $screen_width: 1920,
            $viewport_height: 1080,
            $viewport_width: 1920,
            $lib: 'web',
            $lib_version: '1.30.0',
            $insert_id: 'cp1wsa5ddrwuittb',
            $time: 1671459506.901,
            distinct_id: '18528f8e529264-066928753d330c8-c6a5a43-fa00-18528f8e52bb52',
            $device_id: '18528f8e529264-066928753d330c8-c6a5a43-fa00-18528f8e52bb52',
            $referrer: '$direct',
            $referring_domain: '$direct',
            $active_feature_flags: [],
            token: 'phc_gE7SWBNBgFbA4eQ154KPXebyB8KyLJuypR8jg1DSo9Z',
            $session_id: '18528f8e5361b6d-07f85cfe92fe198-c6a5a43-fa00-18528f8e53714dd',
            $window_id: '1852ac00ad0a8d-03577d57d3a7a08-c6a5a43-1fa400-1852ac00ad159b',
            $set_once: {
                $initial_os: 'Linux',
                $initial_browser: 'Safari',
                $initial_device_type: 'Desktop',
                $initial_current_url:
                    'https://office.getjoan.com/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
                $initial_pathname: '/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
                $initial_browser_version: 16,
                $initial_referrer: '$direct',
                $initial_referring_domain: '$direct',
            },
            $geoip_city_name: 'Brussels',
            $geoip_country_name: 'Belgium',
            $geoip_country_code: 'BE',
            $geoip_continent_name: 'Europe',
            $geoip_continent_code: 'EU',
            $geoip_postal_code: '1000',
            $geoip_latitude: 50.8534,
            $geoip_longitude: 4.347,
            $geoip_time_zone: 'Europe/Brussels',
            $geoip_subdivision_1_code: 'BRU',
            $geoip_subdivision_1_name: 'Brussels Capital',
        },
        timestamp: '2022-12-19T14:18:26.902Z',
        uuid: '01852ac0-0e96-0000-b3b1-d6c1b135c103',
        distinct_id: '18528f8e529264-066928753d330c8-c6a5a43-fa00-18528f8e52bb52',
        ip: '84.198.172.247',
        site_url: 'https://appdata.vnct.xyz',
        team_id: 2,
        now: '2022-12-19T14:18:27.859614+00:00',
        sent_at: '2022-12-19T14:18:26.905000+00:00',
        token: 'phc_gE7SWBNBgFbA4eQ154KPXebyB8KyLJuypR8jg1DSo9Z',
    },
    {
        event: 'SOME/custom_event',
        properties: {
            $os: 'Linux',
            $browser: 'Safari',
            $device_type: 'Desktop',
            $current_url: 'https://office.getjoan.com/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
            $host: 'office.getjoan.com',
            $pathname: '/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
            $browser_version: 16,
            $screen_height: 1080,
            $screen_width: 1920,
            $viewport_height: 1080,
            $viewport_width: 1920,
            $lib: 'web',
            $lib_version: '1.30.0',
            $insert_id: 'cp1wsa5ddrwuittb',
            $time: 1671459506.901,
            distinct_id: '18528f8e529264-066928753d330c8-c6a5a43-fa00-18528f8e52bb52',
            $device_id: '18528f8e529264-066928753d330c8-c6a5a43-fa00-18528f8e52bb52',
            $referrer: '$direct',
            $referring_domain: '$direct',
            $active_feature_flags: [],
            token: 'phc_gE7SWBNBgFbA4eQ154KPXebyB8KyLJuypR8jg1DSo9Z',
            $session_id: '18528f8e5361b6d-07f85cfe92fe198-c6a5a43-fa00-18528f8e53714dd',
            $window_id: '1852ac00ad0a8d-03577d57d3a7a08-c6a5a43-1fa400-1852ac00ad159b',
            $set_once: {
                $initial_os: 'Linux',
                $initial_browser: 'Safari',
                $initial_device_type: 'Desktop',
                $initial_current_url:
                    'https://office.getjoan.com/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
                $initial_pathname: '/device/shareable/1009dea9-5f95-4896-95ec-a12d3397b080',
                $initial_browser_version: 16,
                $initial_referrer: '$direct',
                $initial_referring_domain: '$direct',
            },
            $geoip_city_name: 'Brussels',
            $geoip_country_name: 'Belgium',
            $geoip_country_code: 'BE',
            $geoip_continent_name: 'Europe',
            $geoip_continent_code: 'EU',
            $geoip_postal_code: '1000',
            $geoip_latitude: 50.8534,
            $geoip_longitude: 4.347,
            $geoip_time_zone: 'Europe/Brussels',
            $geoip_subdivision_1_code: 'BRU',
            $geoip_subdivision_1_name: 'Brussels Capital',
        },
        timestamp: '2022-12-19T14:18:26.902Z',
        uuid: '01852ac0-0e96-0000-b3b1-d6c1b135c103',
        distinct_id: '18528f8e529264-066928753d330c8-c6a5a43-fa00-18528f8e52bb52',
        ip: '84.198.172.247',
        site_url: 'https://appdata.vnct.xyz',
        team_id: 2,
        now: '2022-12-19T14:18:27.859614+00:00',
        sent_at: '2022-12-19T14:18:26.905000+00:00',
        token: 'phc_gE7SWBNBgFbA4eQ154KPXebyB8KyLJuypR8jg1DSo9Z',
    },
]

const demoMeta: any = {
    config: { name: 'world' },
    global: {},
    logger: {
        debug: () => {},
        log: () => {},
        error: () => {},
        warn: () => {},
    },
}

test('test processEvent translates utm links correctly revised', () => {
    const utmURL =
        'https://www.reddit.com/r/blender/comments/zmomxw/stable_diffusion_can_texture_your_entire_scene/?utm_source=share&utm_medium=android_app&utm_name=androidcss&utm_term=2&utm_content=share_button'

    demoEvents.forEach((demoEvent) => {
        const utmEvent = {
            ...demoEvent,
            properties: { ...demoEvent.properties, $current_url: utmURL },
        }

        const processedUTMEvent = processEvent(utmEvent, demoMeta)

        expect(processedUTMEvent.properties?.referrer_parser).toBe('utm')

        const googleURL = `https://www.google.com/search?q='joan+6+pro'`

        const referrerEvent = {
            ...demoEvent,
            properties: {
                ...demoEvent.properties,
                $referrer: googleURL,
                $referring_domain: 'google.com',
            },
        }

        const processedReferrerEvent = processEvent(referrerEvent, demoMeta)

        expect(processedReferrerEvent.properties?.referrer_parser).toBe('snowplow')

        const joanURL = `https://office.getjoan.com/settings'`

        const directEvent = {
            ...demoEvent,
            properties: {
                ...demoEvent.properties,
                $referrer: joanURL,
                $referring_domain: 'office.getjoan.com',
            },
        }

        const processedDirectEvent = processEvent(directEvent, demoMeta)

        expect(processedDirectEvent.properties?.referrer_parser).toBe('direct_and_own_domains')
    })
})

test('test processEvent with bad values should not throw', () => {
    const demoEvent = {
        ...demoEvents[0],
        properties: { ...demoEvents[0].properties, $referrer: { foo: 'bar' }, $current_url: false },
    }

    const processedEvent = processEvent(demoEvent, demoMeta)

    expect(processedEvent.properties?.$current_url).toMatchInlineSnapshot(`false`)
})
