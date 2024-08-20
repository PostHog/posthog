import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { now } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { ItemEvent, ItemEventProps } from 'scenes/session-recordings/player/inspector/components/ItemEvent'
import { InspectorListItemEvent } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { mswDecorator } from '~/mocks/browser'
import { RecordingEventType, SessionRecordingPlayerTab } from '~/types'

type Story = StoryObj<typeof ItemEvent>
const meta: Meta<typeof ItemEvent> = {
    title: 'Components/PlayerInspector/ItemEvent',
    component: ItemEvent,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

function makeItem(
    itemOverrides: Partial<InspectorListItemEvent> = {},
    dataOverrides: Partial<RecordingEventType> = {},
    propertiesOverrides: Record<string, any> = {}
): InspectorListItemEvent {
    const data: RecordingEventType = {
        elements: [],
        event: '',
        fullyLoaded: true,
        id: '',
        playerTime: 0,

        timestamp: '',
        ...dataOverrides,
        // this is last so that it overrides data overrides sensibly 🙃
        properties: {
            ...propertiesOverrides,
        },
    }
    return {
        data: data,
        search: '',
        timeInRecording: 0,
        timestamp: now(),
        type: SessionRecordingPlayerTab.EVENTS,
        ...itemOverrides,
    }
}

const BasicTemplate: StoryFn<typeof ItemEvent> = (props: Partial<ItemEventProps>) => {
    const item = makeItem()
    props.item = props.item || item
    props.setExpanded = props.setExpanded || (() => {})

    const propsToUse = props as ItemEventProps

    return (
        <div className="flex flex-col gap-2 min-w-96">
            <h3>Collapsed</h3>
            <ItemEvent {...propsToUse} expanded={false} />
            <LemonDivider />
            <h3>Expanded</h3>
            <ItemEvent {...propsToUse} expanded={true} />
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const PageViewWithPath: Story = BasicTemplate.bind({})
PageViewWithPath.args = {
    item: makeItem({}, { event: '$pageview' }, { $pathname: '/some/path' }),
}

export const PageViewWithCurrentURL: Story = BasicTemplate.bind({})
PageViewWithCurrentURL.args = {
    item: makeItem({}, { event: '$pageview' }, { $current_url: 'https://my-site.io/some/path' }),
}

export const ErrorEvent: Story = BasicTemplate.bind({})
ErrorEvent.args = {
    item: makeItem(
        {},
        { event: '$exception' },
        {
            $exception_message: 'Something went wrong',
            $exception_type: 'Error',
            $exception_personURL: 'https://my-site.io/person/123',
            $lib: 'web',
            $lib_version: '1.187.234',
            $browser: 'Chrome',
            $browser_version: 180,
            $os: 'Windows',
            $os_version: '11',
        }
    ),
}

export const SentryErrorEvent: Story = BasicTemplate.bind({})
SentryErrorEvent.args = {
    item: makeItem(
        {},
        { event: '$exception' },
        {
            $sentry_url: 'https://some-sentry-url',
            $exception_message: 'Something went wrong',
            $exception_type: 'Error',
            $exception_personURL: 'https://my-site.io/person/123',
            $lib: 'web',
            $lib_version: '1.187.234',
            $browser: 'Chrome',
            $browser_version: 180,
            $os: 'Windows',
            $os_version: '11',
        }
    ),
}

export const WebVitalsEvent: Story = BasicTemplate.bind({})
WebVitalsEvent.args = {
    item: makeItem(
        {},
        { event: '$web_vitals' },
        {
            $os: 'Mac OS X',
            $os_version: '10.15.7',
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $current_url: 'http://localhost:8000/project/1/activity/explore',
            $browser_version: 126,
            $browser_language: 'en-GB',
            $lib: 'web',
            $lib_version: '1.141.4',
            $web_vitals_enabled_server_side: false,
            $web_vitals_INP_event: {
                name: 'INP',
                value: 72,
                rating: 'good',
                delta: 72,
                entries: [{}, {}],
                id: 'v4-1719484470693-6845621238957',
                navigationType: 'reload',
                $current_url: 'http://localhost:8000/project/1/activity/explore',
                $session_id: '0190593b-0f3c-7e04-846a-f3515aa31c2f',
                $window_id: '01905942-b7ba-7c05-85d3-5d7548868b44',
                timestamp: 1719484490693,
            },
            $web_vitals_INP_value: 72,
            $web_vitals_CLS_event: {
                name: 'CLS',
                value: 0.10656105463687347,
                rating: 'needs-improvement',
                delta: 0.10656105463687347,
                entries: [{}, {}, {}, {}, {}, {}, {}, {}, {}],
                id: 'v4-1719484470710-6118725051157',
                navigationType: 'reload',
                $current_url: 'http://localhost:8000/project/1/activity/explore',
                $session_id: '0190593b-0f3c-7e04-846a-f3515aa31c2f',
                $window_id: '01905942-b7ba-7c05-85d3-5d7548868b44',
                timestamp: 1719484490693,
            },
            $web_vitals_CLS_value: 0.10656105463687347,
        }
    ),
}

export const GroupIdentifyEvent: Story = BasicTemplate.bind({})
GroupIdentifyEvent.args = {
    item: makeItem(
        {},
        { event: '$groupidentify' },
        {
            $os: 'Mac OS X',
            $os_version: '10.15.7',
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $current_url: 'https://us.posthog.com/project/2/insights/new',
            $host: 'us.posthog.com',
            $pathname: '/project/2/insights/new',
            $raw_user_agent:
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            $browser_version: 127,
            $browser_language: 'en-US',
            $screen_height: 1080,
            $screen_width: 1920,
            $viewport_height: 934,
            $viewport_width: 1920,
            $lib: 'web',
            $lib_version: '1.157.1',
            $insert_id: '6la51dyujzjgc19m',
            $time: 1724165889.123,
            distinct_id: '48vHN2rW28SvzA6D4NdgHajLOjBP1ulsI0Rr5DNas4i',
            $device_id: '0190e039-823d-7987-9e87-3d1ec9f325b1',
            $initial_person_info: {
                r: '$direct',
                u: 'https://us.posthog.com/project/2',
            },
            $groups: {
                project: 'fc445b88-e2c4-488e-bb52-aa80cd7918c9',
                organization: '4dc8564d-bd82-1065-2f40-97f7c50f67cf',
                customer: 'cus_IK2DWsWVn2ZM16',
                instance: 'https://us.posthog.com',
            },
            realm: 'cloud',
            email_service_available: true,
            slack_service_available: true,
            commit_sha: '8c1d243eb5',
            $referrer: '$direct',
            $referring_domain: '$direct',
            $group_type: 'instance',
            $group_key: 'https://us.posthog.com',
            $group_set: {
                site_url: 'https://us.posthog.com',
            },
            token: 'sTMFPsFhdP1Ssg',
            $session_id: '01917043-b2a1-7c2e-a57e-6db514bde084',
            $window_id: '01917043-b2a1-7c2e-a57e-6db6676bb4a1',
            $lib_custom_api_host: 'https://internal-t.posthog.com',
            $is_identified: true,
            $lib_rate_limit_remaining_tokens: 85.46,
            $ip: '67.84.74.189',
            $initial_person_info__r: '$direct',
            $initial_person_info__u: 'https://us.posthog.com/project/2',
            $surveys_activated__0: '0190fe51-92a0-0000-4ba3-f85f5f0ef78f',
            $lib_version__major: 1,
            $lib_version__minor: 157,
            $lib_version__patch: 1,
            $group_2: 'fc445b88-e2c4-488e-bb52-aa80cd7918c9',
            $group_0: '4dc8564d-bd82-1065-2f40-97f7c50f67cf',
            $group_3: 'cus_IK2DWsWVn2ZM16',
            $group_1: 'https://us.posthog.com',
        }
    ),
}
