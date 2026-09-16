import { Meta, StoryObj } from '@storybook/react'

import { BackupCodesList } from './BackupCodesList'

const meta: Meta<typeof BackupCodesList> = {
    title: 'Components/Backup Codes List',
    component: BackupCodesList,
}
export default meta

type Story = StoryObj<typeof BackupCodesList>

export const Default: Story = {
    args: {
        codes: ['4hj2kd91', '9wq3mz07', 'p1x8vn46', 'z7c5tb20', 'r3f9ks81'],
    },
}
