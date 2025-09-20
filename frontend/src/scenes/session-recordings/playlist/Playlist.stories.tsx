import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { range } from 'lib/utils'

import { SessionRecordingType } from '~/types'

import { Playlist, PlaylistProps } from '../playlist/Playlist'

type Story = StoryObj<typeof Playlist>
const meta: Meta<typeof Playlist> = {
    title: 'Components/Playlist',
    component: Playlist,
}
export default meta

type ObjectType = { id: string | number }

const ListItem = ({ item }: { item: ObjectType }): JSX.Element => <div className="p-1">Object {item.id}</div>

const Template: StoryFn<typeof Playlist> = (props: Partial<PlaylistProps>) => {
    const mainContent = ({ activeItem }: { activeItem: SessionRecordingType }): JSX.Element => (
        <div className="flex items-center justify-center h-full">
            {activeItem ? `Object ${activeItem.id} selected` : 'Select an item from the list'}
        </div>
    )

    return (
        <div className="h-96 min-w-[40rem]">
            <Playlist
                title="Title"
                sections={[]}
                listEmptyState={<div>No items</div>}
                content={mainContent}
                {...props}
            />
        </div>
    )
}

export const Default: Story = Template.bind({})
Default.args = {
    sections: [
        {
            key: 'default',
            title: 'Default section',
            items: range(0, 100).map((idx) => ({ id: idx }) as unknown as SessionRecordingType),
            render: ListItem,
        },
    ],
}

export const MultipleSections: Story = Template.bind({})
MultipleSections.args = {
    sections: [
        {
            key: 'one',
            title: 'First section',
            items: range(0, 5).map((idx) => ({ id: idx }) as unknown as SessionRecordingType),
            render: ListItem,
            initiallyOpen: true,
        },
        {
            key: 'two',
            title: 'Second section',
            items: range(0, 5).map((idx) => ({ id: idx }) as unknown as SessionRecordingType),
            render: ListItem,
        },
    ],
}

export const WithFooter: Story = Template.bind({})
WithFooter.args = {
    sections: [
        {
            key: 'default',
            title: 'Section with footer',
            items: range(0, 100).map((idx) => ({ id: idx }) as unknown as SessionRecordingType),
            render: ListItem,
            footer: <div className="px-1 py-3">Section footer</div>,
        },
    ],
}
