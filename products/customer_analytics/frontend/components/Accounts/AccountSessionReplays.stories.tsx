import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'
import type { SessionRecordingType } from '~/types'

import { AccountSessionReplays } from './AccountSessionReplays'

const RECORDINGS_ENDPOINT = 'api/projects/:team_id/session_recordings/'
const recordings: SessionRecordingType[] = [0, 1, 2].map((index) => ({
    id: `example-recording-${index}`,
    viewed: false,
    viewers: [],
    recording_duration: 90 + index * 30,
    start_time: `2026-06-01T1${2 - index}:00:00Z`,
    end_time: `2026-06-01T1${2 - index}:02:00Z`,
    snapshot_source: 'web',
    start_url: 'https://example.com/settings',
    click_count: 3,
    keypress_count: 12,
    person: {
        id: String(42 + index),
        uuid: `11111111-2222-4333-8444-55555555555${index}`,
        name: `Example user ${index + 1}`,
        distinct_ids: [`example-user-${index}`],
        properties: {},
    },
}))

const meta: Meta<typeof AccountSessionReplays> = {
    title: 'Customer Analytics/Account views/Session replays',
    component: AccountSessionReplays,
    args: { accountId: 'example-account', externalId: 'example-account-key', instanceId: 'example-replay-tile' },
    parameters: {
        mockDate: '2026-06-02T12:00:00Z',
        testOptions: { waitForSelector: '[data-attr="account-replays-open-recording"]' },
    },
    decorators: [
        (Story, { parameters }) => {
            useEffect(() => {
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...MOCK_DEFAULT_TEAM,
                    customer_analytics_config: {
                        ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                        account_group_type_index: 0,
                    },
                })
            }, [])
            return (
                <div className={parameters.narrow ? 'w-128 p-2' : 'w-192 p-2'}>
                    <Story />
                </div>
            )
        },
    ],
}
export default meta

type Story = StoryObj<typeof AccountSessionReplays>

const recordingsMocks = mswDecorator({
    get: {
        [RECORDINGS_ENDPOINT]: ({ request }: MockResolverInfo) => {
            const params = new URL(request.url).searchParams
            const filtered = params.get('person_uuid')
                ? recordings.filter((recording) => recording.person?.uuid === params.get('person_uuid'))
                : recordings
            return {
                results: params.has('after') ? [recordings[2]] : filtered.slice(0, 2),
                has_next: !params.has('after') && !params.has('person_uuid'),
                next_cursor: params.has('after') ? undefined : 'example-cursor',
            }
        },
    },
})

export const Recordings: Story = { decorators: [recordingsMocks] }

export const Narrow: Story = { parameters: { narrow: true }, decorators: [recordingsMocks] }

const overflowRecordings: SessionRecordingType[] = Array.from({ length: 40 }, (_, index) => ({
    ...recordings[index % recordings.length],
    id: `example-overflow-recording-${index}`,
    recording_duration: 120,
    start_time: new Date(Date.UTC(2026, 5, 1, 12, -index)).toISOString(),
    end_time: new Date(Date.UTC(2026, 5, 1, 12, 2 - index)).toISOString(),
    start_url: index % 2 === 0 ? 'https://example.com/settings' : undefined,
}))

const overflowMocks = mswDecorator({
    get: {
        [RECORDINGS_ENDPOINT]: ({ request }: MockResolverInfo) => {
            const params = new URL(request.url).searchParams
            const filtered = params.get('person_uuid')
                ? overflowRecordings.filter((recording) => recording.person?.uuid === params.get('person_uuid'))
                : overflowRecordings
            const offset = params.has('after') ? 20 : 0
            const hasNext = filtered.length > offset + 20
            return {
                results: filtered.slice(offset, offset + 20),
                has_next: hasNext,
                next_cursor: hasNext ? 'example-overflow-cursor' : undefined,
            }
        },
    },
})

export const Overflow: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="account-replays-list"][data-height-ready="true"]' } },
    decorators: [overflowMocks],
}

export const OverflowNarrow: Story = {
    parameters: {
        narrow: true,
        testOptions: { waitForSelector: '[data-attr="account-replays-list"][data-height-ready="true"]' },
    },
    decorators: [overflowMocks],
}

export const Loading: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="account-replays-loading"]' } },
    decorators: [
        mswDecorator({
            get: {
                [RECORDINGS_ENDPOINT]: async () => {
                    return new Promise<never>(() => {})
                },
            },
        }),
    ],
}

export const Empty: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="account-replays-empty"]' } },
    decorators: [mswDecorator({ get: { [RECORDINGS_ENDPOINT]: { results: [], has_next: false } } })],
}

export const Setup: Story = {
    args: { externalId: '' },
    parameters: { testOptions: { waitForSelector: '[data-attr="account-replays-setup"]' } },
}

export const Denied: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="account-replays-denied"]' } },
    decorators: [mswDecorator({ get: { [RECORDINGS_ENDPOINT]: [403, { detail: 'Access denied' }] } })],
}

export const Error: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="account-replays-error"]' } },
    decorators: [mswDecorator({ get: { [RECORDINGS_ENDPOINT]: [500, { detail: 'Request failed' }] } })],
}
