import type { Meta, StoryObj } from '@storybook/react'

import { ActivityClientTag, ActivityClientTagProps } from './ActivityClientTag'

type Story = StoryObj<ActivityClientTagProps>
const meta: Meta<ActivityClientTagProps> = {
    title: 'Components/ActivityClientTag',
    component: ActivityClientTag,
    parameters: {},
}
export default meta

export const Mcp: Story = {
    args: { client: 'mcp' },
}

export const Scout: Story = {
    args: { client: 'scout:self-driving-dwh' },
}

export const Sdk: Story = {
    args: { client: 'posthog-js/1.234.0' },
}
