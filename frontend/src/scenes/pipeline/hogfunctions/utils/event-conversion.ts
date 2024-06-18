import { HogFunctionInvocationGlobals } from '~/types'

// NOTE: This is just for testing - follow up change will derive this from real events
export const createExampleGlobals = (): Partial<HogFunctionInvocationGlobals> => ({
    event: {
        uuid: '018f0a66-da7b-0000-94cf-ec29cbb4591a',
        name: 'Demo Event',
        distinct_id: '12345',
        properties: {
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $current_url: `${window.location.origin}/project/1/activity/explore`,
            $pathname: '/project/1/activity/explore',
            $browser_version: 125,
        },
        timestamp: '2024-06-17T09:31:41.507000+00:00',
        url: `${window.location.origin}/project/1/activity/explore`,
    },
    person: {
        uuid: '018f0a66-d9ce-0000-6bf0-0f045191d4a8',
        name: 'Demo Person',
        url: `${window.location.origin}/person/018f0a66-d9ce-0000-6bf0-0f045191d4a8`,
        properties: {
            email: 'example@posthog.com',
        },
    },
})
