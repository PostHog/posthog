import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/Persons & Groups',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings/': () => {
                    return [
                        200,
                        {
                            results: [
                                {
                                    id: 'mango-0000-avocado-1111',
                                    distinct_id: 'grape-2222-kiwi-3333',
                                    viewed: false,
                                    viewers: [],
                                    recording_duration: 351,
                                    active_seconds: 24,
                                    inactive_seconds: 326,
                                    start_time: '2023-07-04T22:53:48.554000Z',
                                    end_time: '2023-07-04T22:59:39.681000Z',
                                    click_count: 7,
                                    keypress_count: 12,
                                    mouse_activity_count: 72,
                                    console_log_count: 2,
                                    console_warn_count: 0,
                                    console_error_count: 7,
                                    start_url: 'https://us.posthog.com/signup/pineapple-aaaa-bbbb-cccc-123456789abc',
                                    person: {
                                        id: 99999999999,
                                        name: 'banana@veggie.ai',
                                        distinct_ids: ['grape-2222-kiwi-3333'],
                                        properties: {
                                            $os: 'Mac OS X',
                                            email: 'banana@veggie.ai',
                                            clearbit: {
                                                company: {
                                                    id: 'lettuce-9876-spinach-5432',
                                                    geo: {
                                                        city: 'Vegville',
                                                        state: 'Greensylvania',
                                                        country: 'Vegetaria',
                                                        postalCode: '12345',
                                                        streetAddress: '101 Kale Avenue',
                                                    },
                                                    logo: 'https://logo.clearbit.com/veggie.ai',
                                                    name: 'Veggie Inc.',
                                                    site: {
                                                        phoneNumbers: ['+1 555-CABBAGE'],
                                                        emailAddresses: ['info@veggie.ai'],
                                                    },
                                                    location: '101 Kale Ave, Vegville, VG 12345, Vegetaria',
                                                },
                                            },
                                            org__name: 'Veggie Inc.',
                                            project_id: 'fig-1234-plum-5678',
                                            $geoip_city_name: 'Tomatotown',
                                            $geoip_country_name: 'Vegetaria',
                                            $initial_geoip_city_name: 'Cabbage City',
                                            $initial_geoip_country_name: 'Vegetaria',
                                            $creator_event_uuid: 'pumpkin-4444-turnip-8888',
                                            organization_id: 'radish-7777-leek-9999',
                                        },
                                        created_at: '2025-05-08T22:53:38.784000Z',
                                        uuid: 'carrot-1234-parsnip-5678',
                                    },
                                    storage: 'object_storage',
                                    snapshot_source: 'web',
                                    ongoing: false,
                                    activity_score: 11.62,
                                },
                            ],
                            message:
                                'Generic GET to /api/environments/:team_id/session_recordings/ mock for PersonSceneStory',
                        },
                    ]
                },
            },
            post: {
                '/api/environments/:team_id/query/': (req) => {
                    const query = (req.body as any)?.query
                    // Check if it's a DataTableNode query, which is used for Events/Exceptions tabs
                    if (
                        query &&
                        query.kind === 'HogQLQuery' &&
                        query.values.id === '741cc6c0-7c48-55f2-9b58-1b648a381c9e'
                    ) {
                        return [
                            200,
                            {
                                columns: ['id', 'distinct_ids', 'properties', 'is_identified', 'created_at'],
                                results: [
                                    [
                                        'b4957134-eae2-58b2-ab91-012b73df0b91',
                                        [
                                            '0196b21a-dffa-78e4-a0f9-7a0994dcd0ad',
                                            '4qJcD956scT7OP7fAYnG7kyqW3hNU8eRhlH6kjaPY5S',
                                        ],
                                        '{"$os": "Mac OS X", "_kx": null, "epik": null, "$host": "us.posthog.com", "dclid": null, "email": "tomato@fruit.ai", "gclid": null, "qclid": null, "realm": "cloud", "sccid": null, "fbclid": null, "gbraid": null, "gclsrc": null, "igshid": null, "irclid": null, "mc_cid": null, "ttclid": null, "twclid": null, "wbraid": null, "msclkid": null, "rdt_cid": null, "$browser": "Chrome", "clearbit": {"person": null, "company": {"id": "eggplant-1234-pepper-5678", "geo": {"lat": 12.345678, "lng": -98.765432, "city": "Zucchini", "state": "Cucumber", "country": "Fruitland", "stateCode": "CU", "postalCode": "12345", "streetName": "Radish Road", "subPremise": null, "countryCode": "VE", "streetNumber": "42", "streetAddress": "42 Radish Road"}, "logo": "https://logo.clearbit.com/celery.ai", "name": "Celery Inc.", "site": {"phoneNumbers": ["+1 555-VEG-FOOD"], "emailAddresses": ["help@celery.ai"]}, "tags": ["Vegetable Technology", "Snackware"], "tech": ["carrot_cloud", "onion_mail"], "type": "private", "phone": "+1 555-VEG-FOOD", "domain": "celery.ai", "parent": {"domain": null}, "metrics": {"employees": null}, "linkedin": {"handle": "company/celery"}, "location": "42 Radish Rd, Zucchini, CU 12345, Fruitland", "timeZone": "America/Squash", "description": "Fresh vegetable analytics"}}, "icp_role": "marketing", "joined_at": "2025-05-08T22:54:11.324026+00:00", "org__name": "Celery", "project_id": "banana-1234-grape-5678", "$initial_os": "Linux", "$os_version": "10.15.7", "$current_url": "https://us.posthog.com/", "$device_type": "Desktop", "$screen_width": 3440, "$screen_height": 1440, "$geoip_latitude": 10.101, "$geoip_longitude": -20.202, "$geoip_city_name": "Avocadoville", "$geoip_postal_code": "54321", "$geoip_country_code": "FR", "$geoip_country_name": "Fruitland", "$initial_geoip_city_name": "Berryville", "$initial_geoip_latitude": 12.1212, "$initial_geoip_longitude": -34.3434, "$initial_geoip_postal_code": "67890", "$initial_geoip_country_name": "Fruitland", "$creator_event_uuid": "pineapple-9876-cherry-5432", "organization_id": "grapefruit-0000-apple-9999"}',
                                        1,
                                        '2025-05-08T15:53:38-07:00',
                                    ],
                                ],
                                hasMore: false,
                                is_cached: true,
                                cache_key: 'test-datatable',
                                calculation_trigger: null,
                                error: '',
                                query_status: null,
                            },
                        ]
                    }
                    // Fallback for other POST /api/query calls that might not be DataTableNode
                    // For example, if other components on this page make different query calls.
                    // You might need to make this more specific if there are multiple non-DataTableNode POSTs.
                    return [200, { results: [], message: 'Generic POST to /api/query mock for PersonSceneStory' }]
                },
            },
        }),
    ],
}
export default meta

export const PersonNotFound: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.personByUUID('not-found'))
    }, [])

    return <App />
}

export const Person: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.personByUUID('741cc6c0-7c48-55f2-9b58-1b648a381c9e'))
    }, [])

    return <App />
}

export const PersonRecordingTab: StoryFn = () => {
    useEffect(() => {
        router.actions.push(`${urls.personByUUID('741cc6c0-7c48-55f2-9b58-1b648a381c9e')}#activeTab=sessionRecordings`)
    }, [])

    return <App />
}
