import type { Meta, StoryObj } from '@storybook/react'

import { SignupPasswordStrength } from './SignupPasswordStrength'

const meta: Meta<typeof SignupPasswordStrength> = {
    title: 'Scenes-Other/Authentication/Signup password strength',
    component: SignupPasswordStrength,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    decorators: [
        (Story) => (
            <div className="max-w-96">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SignupPasswordStrength>

export const Empty: Story = { args: { password: '' } }
export const Weak: Story = { args: { password: 'password123' } }
export const TenSeconds: Story = { args: { password: 'Q7!mK2@rL9#' } }
export const Medium: Story = { args: { password: 'violet-satellite-otter7' } }
export const Strong: Story = { args: { password: 'violet-satellite-otter-cobalt' } }
export const Extreme: Story = { args: { password: 'rT9!kL2@vZ8#qM4$xB7%nF3&' } }
