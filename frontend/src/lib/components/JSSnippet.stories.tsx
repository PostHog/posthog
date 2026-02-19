import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { JSSnippet } from './JSSnippet'

const meta: Meta<typeof JSSnippet> = {
    title: 'Components/JSSnippet',
    component: JSSnippet,
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/proxy_records': [],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof JSSnippet>

export const Default: Story = {}
