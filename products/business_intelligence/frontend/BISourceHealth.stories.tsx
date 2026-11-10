import { Meta, StoryObj } from '@storybook/react'

import { BISourceHealth } from './BISourceHealth'

const meta: Meta<typeof BISourceHealth> = {
    title: 'Products/Business intelligence/Source health',
    component: BISourceHealth,
    args: {
        health: {
            subject_type: 'table',
            subject_uuid: 'example',
            health: 'failing',
            checks_total: 3,
            checks_failing: 1,
        },
        loading: false,
        error: false,
        retry: () => {},
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const Failing: Story = {}
export const Unchecked: Story = {
    args: {
        health: {
            subject_type: 'table',
            subject_uuid: 'example',
            health: 'unknown',
            checks_total: 0,
            checks_failing: 0,
        },
    },
}
export const Unavailable: Story = { args: { health: null } }
export const Error: Story = { args: { health: null, error: true } }
