import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { QueryTab } from './multitabEditorLogic'
import { QueryTabs } from './QueryTabs'

type Story = StoryObj<typeof QueryTabs>
const meta: Meta<typeof QueryTabs> = {
    title: 'Scenes-App/Data Warehouse/QueryTabs',
    component: QueryTabs,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof QueryTabs> = (args) => {
    return <QueryTabs {...args} />
}

const mockModels: QueryTab[] = [
    {
        uri: { path: '/query1.sql', scheme: 'file' },
        name: 'Query 1',
        view: null,
        active: true,
    },
    {
        uri: { path: '/query2.sql', scheme: 'file' },
        name: 'Query 2',
        view: null,
    },
]

export const Default: Story = Template.bind({})
Default.args = {
    models: mockModels,
    activeModelUri: mockModels[0],
}

export const SingleTab: Story = Template.bind({})
SingleTab.args = {
    models: [mockModels[0]],
    // @ts-expect-error
    activeModelUri: mockModels[0],
}

export const NoActiveTabs: Story = Template.bind({})
NoActiveTabs.args = {
    models: mockModels,
    activeModelUri: null,
}
