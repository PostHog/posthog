import type { Meta, StoryObj } from '@storybook/react'

import { CheckStatusCell } from './CheckStatusCell'

const meta: Meta<typeof CheckStatusCell> = {
    title: 'Products/Data quality/Check status',
    component: CheckStatusCell,
    args: {
        check: { last_status: '', last_succeeded_at: null, failing_since: null, subject_status: 'needs_review' },
    },
}
export default meta

type Story = StoryObj<typeof CheckStatusCell>
export const NeedsReview: Story = {}
export const NotRunYet: Story = {
    args: { check: { last_status: '', last_succeeded_at: null, failing_since: null, subject_status: 'active' } },
}
