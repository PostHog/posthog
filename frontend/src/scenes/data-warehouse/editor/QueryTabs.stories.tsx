import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { Uri, UriComponents } from 'monaco-editor'

import { multitabEditorLogic, QueryTab } from './multitabEditorLogic'
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
    return (
        <BindLogic logic={multitabEditorLogic} props={{ key: 'new' }}>
            <QueryTabs {...args} />
        </BindLogic>
    )
}

const mockModels: QueryTab[] = [
    {
        uri: {
            path: '/query1.sql',
            scheme: 'file',
            authority: '',
            query: '',
            fragment: '',
            fsPath: '',
            with: function (change: {
                scheme?: string
                authority?: string | null
                path?: string | null
                query?: string | null
                fragment?: string | null
            }): Uri {
                change.path = '/query1.sql'
                return this
            },
            toJSON: function (): UriComponents {
                return {
                    path: '/query1.sql',
                    scheme: 'file',
                    authority: '',
                    query: '',
                    fragment: '',
                }
            },
        },
        name: 'Query 1',
        view: undefined,
        level: 'source',
    },
    {
        uri: {
            path: '/query2.sql',
            scheme: 'file',
            authority: '',
            query: '',
            fragment: '',
            fsPath: '',
            with: function (change: {
                scheme?: string
                authority?: string | null
                path?: string | null
                query?: string | null
                fragment?: string | null
            }): Uri {
                change.path = '/query1.sql'
                return this
            },
            toJSON: function (): UriComponents {
                return {
                    path: '/query1.sql',
                    scheme: 'file',
                    authority: '',
                    query: '',
                    fragment: '',
                }
            },
        },
        name: 'Query 2',
        level: 'source',
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
    activeModelUri: mockModels[0],
}

export const NoActiveTabs: Story = Template.bind({})
NoActiveTabs.args = {
    models: mockModels,
    activeModelUri: null,
}
