import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'

// NOTE: This is just for testing - it technically returns ParsedClickhouseEvent but not worth it to import that type
export const createExampleEvent = (): any => ({
    uuid: uuid(),
    event: '$pageview',
    distinct_id: '12345',
    properties: {
        $browser: 'Chrome',
        $device_type: 'Desktop',
        $current_url: `${window.location.origin}/project/1/activity/explore`,
        $pathname: '/project/1/activity/explore',
        $browser_version: 125,
    },
    timestamp: dayjs().toISOString(),
    created_at: dayjs().toISOString(),
    url: `${window.location.origin}/project/1/activity/explore`,
    person_id: uuid(),
    person_created_at: dayjs().toISOString(),
    person_properties: {
        email: 'user@example.com',
    },
})
