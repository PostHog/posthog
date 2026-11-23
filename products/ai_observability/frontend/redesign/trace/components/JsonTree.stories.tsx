import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../storyFixtures'
import { JsonTree } from './JsonTree'

const meta: Meta<typeof JsonTree> = {
    title: 'Scenes-App/AI observability/Trace view/JSON tree',
    component: JsonTree,
    args: {
        src: {
            content: [
                {
                    type: 'text',
                    text: {
                        rows: [
                            {
                                order: 'A-1001',
                                status: 'shipped',
                                note: 'Left at the front desk after two delivery attempts.',
                            },
                            { order: 'A-1002', status: 'pending', note: null },
                        ],
                        next_page: { cursor: 'c2', has_more: true },
                    },
                },
            ],
            is_error: false,
        },
    },
}
export default meta

type Story = StoryObj<typeof JsonTree>

export const Default: Story = { parameters: { testOptions: { snapshotBrowsers: [] } } }
export const Narrow: Story = { decorators: [withWidth(320)] }
export const SearchMatch: Story = {
    args: { highlightQuery: 'has_more' },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
