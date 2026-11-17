import type { Meta, StoryObj } from '@storybook/react'

import { loadPasswordEstimator, validatePassword } from 'lib/components/PasswordStrength'

import { SignupPasswordStrength } from './SignupPasswordStrength'

const meta: Meta<{ password: string }> = {
    title: 'Scenes-Other/Authentication/Signup password strength',
    parameters: { testOptions: { snapshotBrowsers: [] } },
    loaders: [async () => ({ estimatorReady: await loadPasswordEstimator() })],
    render: ({ password }) => (
        <SignupPasswordStrength
            password={password}
            validatedPassword={validatePassword(password)}
            estimatorLoading={false}
        />
    ),
    decorators: [
        (Story) => (
            <div className="max-w-96">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<{ password: string }>

export const Empty: Story = { args: { password: '' } }
export const Weak: Story = { args: { password: 'password123' } }
export const TenSeconds: Story = { args: { password: 'Q7!mK2@rL9#' } }
export const Medium: Story = { args: { password: 'violet-satellite-otter7' } }
export const Strong: Story = { args: { password: 'violet-satellite-otter-cobalt' } }
export const Extreme: Story = { args: { password: 'rT9!kL2@vZ8#qM4$xB7%nF3&' } }
