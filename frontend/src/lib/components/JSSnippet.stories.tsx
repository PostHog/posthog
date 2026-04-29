import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { JSSnippet } from './JSSnippet'

const meta: Meta = {
    title: 'Components/JSSnippet',
    component: JSSnippet,
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/proxy_records': [],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    parameters: {
        testOptions: {
            snapshotBrowsers: [], // Non-deterministic width causes intermittent snapshot failures
        },
    },
}
