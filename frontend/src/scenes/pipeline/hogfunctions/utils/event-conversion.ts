import { HogFunctionInvocationGlobals } from '~/types'

export const createExampleGlobals = (): HogFunctionInvocationGlobals => ({
    project: {
        id: 1,
        name: 'Demo Project',
        url: 'http://localhost:8000/project/1',
    },
    source: {
        name: 'HogFuns',
        url: window.location.origin,
    },
    event: {
        uuid: '018f0a66-da7b-0000-94cf-ec29cbb4591a',
        name: 'Demo Event',
        distinct_id: '10E49yv2TpBJNPPNBcW30LNbZjclPlRS0FQTjlJ2hzq',
        properties: {
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $current_url: 'http://localhost:8000/project/1/activity/explore',
            $pathname: '/project/1/activity/explore',
            $browser_version: 125,
            $referrer:
                'http://localhost:8000/project/1/pipeline/destinations/hog-01901610-75a4-0000-9dbb-dc84db437472/configuration',
            $referring_domain: 'localhost:8000',
        },
        timestamp: '2024-06-17T09:31:41.507000+00:00',
        url: 'http://localhost:8000/project/1/activity/explore',
    },
    person: {
        uuid: '018f0a66-d9ce-0000-6bf0-0f045191d4a8',
        name: 'Demo Person',
        url: 'http://localhost:8000/person/018f0a66-d9ce-0000-6bf0-0f045191d4a8',
        properties: {
            $group_0: '018f0a66-da7b-0000-94cf-ec29cbb4591a',
            $group_1: '018f0a66-d9ce-0000-6bf0-0f045191d4a8',
            $group_4: 'cus_PznULFAg9uznrD',
            $group_2: 'http://localhost:8000',
        },
    },
    groups: {
        $group_0: {
            id: '018f0a66-da7b-0000-94cf-ec29cbb4591a',
            type: 'group',
            index: 0,
            url: 'http://localhost:8000/group/018f0a66-da7b-0000-94cf-ec29cbb4591a',
            properties: {},
        },
        $group_1: {
            id: '018f0a66-d9ce-0000-6bf0-0f045191d4a8',
            type: 'group',
            index: 1,
            url: 'http://localhost:8000/group/018f0a66-d9ce-0000-6bf0-0f045191d4a8',
            properties: {},
        },
        $group_4: {
            id: 'cus_PznULFAg9uznrD',
            type: 'customer',
            index: 4,
            url: 'http://localhost:8000/customer/cus_PznULFAg9uznrD',
            properties: {},
        },
        $group_2: {
            id: 'http://localhost:8000',
            type: 'url',
            index: 2,
            url: 'http://localhost:8000',
            properties: {},
        },
    },
})
