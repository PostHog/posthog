import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { range } from 'lib/utils'

import { SessionRecordingType } from '~/types'

import { Playlist, PlaylistProps } from '../playlist/Playlist'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

type Story = StoryObj<typeof Playlist>
const meta: Meta<typeof Playlist> = {
    title: 'Components/Playlist',
    component: Playlist,
}
export default meta

const mockRecordings = (count: number): SessionRecordingType[] =>
    range(0, count).map((idx) => ({
        id: `recording-${idx}`,
        start_time: '2024-01-15T10:00:00Z',
        end_time: '2024-01-15T10:05:00Z',
        recording_duration: 120 + idx * 10,
        viewed: idx % 3 === 0,
        click_count: 10 + idx,
        keypress_count: 5 + idx,
        start_url: `https://example.com/page-${idx}`,
        person: {
            distinct_ids: [`user-${idx}`],
            properties: {
                email: `user${idx}@example.com`,
                $browser: 'Chrome',
                $os: 'Mac OS X',
                $device_type: 'Desktop',
                $geoip_country_code: 'US',
            },
        },
    })) as SessionRecordingType[]

const logicProps = { logicKey: 'story' }

const Template: StoryFn<typeof Playlist> = (props: Partial<PlaylistProps>) => {
    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="h-96 w-[40rem]">
                <Playlist
                    title="Title"
                    pinnedRecordings={[]}
                    otherRecordings={[]}
                    listEmptyState={<div>No items</div>}
                    {...props}
                />
            </div>
        </BindLogic>
    )
}

export const Default: Story = Template.bind({})
Default.args = {
    otherRecordings: mockRecordings(100),
}

export const WithPinnedRecordings: Story = Template.bind({})
WithPinnedRecordings.args = {
    pinnedRecordings: mockRecordings(5),
    otherRecordings: mockRecordings(20),
}

export const WithLoadMore: Story = Template.bind({})
WithLoadMore.args = {
    otherRecordings: mockRecordings(10),
    hasNext: true,
}

export const Empty: Story = Template.bind({})
Empty.args = {
    pinnedRecordings: [],
    otherRecordings: [],
}

const WideTemplate: StoryFn<typeof Playlist> = (props: Partial<PlaylistProps>) => {
    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="h-96 w-[50rem]">
                <Playlist
                    title="Title"
                    pinnedRecordings={[]}
                    otherRecordings={mockRecordings(10)}
                    listEmptyState={<div>No items</div>}
                    {...props}
                />
            </div>
        </BindLogic>
    )
}

export const WideLayout: Story = WideTemplate.bind({})
WideLayout.args = {}
WideLayout.parameters = {
    docs: {
        description: {
            story: 'Playlist at wide container width (50rem) - shows full property and activity labels',
        },
    },
}

const NarrowTemplate: StoryFn<typeof Playlist> = (props: Partial<PlaylistProps>) => {
    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="h-96 w-64">
                <Playlist
                    title="Title"
                    pinnedRecordings={[]}
                    otherRecordings={mockRecordings(10)}
                    listEmptyState={<div>No items</div>}
                    {...props}
                />
            </div>
        </BindLogic>
    )
}

export const NarrowLayout: Story = NarrowTemplate.bind({})
NarrowLayout.args = {}
NarrowLayout.parameters = {
    docs: {
        description: {
            story: 'Playlist at narrow container width (16rem) - hides property and activity labels',
        },
    },
}
