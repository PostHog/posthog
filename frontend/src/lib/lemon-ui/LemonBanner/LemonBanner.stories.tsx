import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonBanner, LemonBannerProps } from './LemonBanner'

type Story = StoryObj<typeof LemonBanner>
const meta: Meta<typeof LemonBanner> = {
    title: 'Lemon UI/Lemon Banner',
    component: LemonBanner,
    tags: ['autodocs'],
    parameters: {
        actions: {
            // See https://github.com/storybookjs/addon-smart-knobs/issues/63#issuecomment-995798227
            argTypesRegex: null,
        },
    },
}
export default meta
const Template: StoryFn<typeof LemonBanner> = (props: LemonBannerProps) => {
    return <LemonBanner {...props} />
}

export const Info: Story = {
    render: Template,
    args: { type: 'info', children: 'PSA: Every dish can be improved by adding more garlic.' },
}

export const Warning: Story = {
    render: Template,
    args: { type: 'warning', children: 'This spacecraft is about to explode. Please evacuate immediately.' },
}

export const Error: Story = {
    render: Template,
    args: { type: 'error', children: 'This spacecraft has exploded. Too late...' },
}

export const Success: Story = {
    render: Template,
    args: { type: 'success', children: 'This spacecraft has recovered. Phew!' },
}

export const Closable: Story = {
    render: Template,

    args: {
        type: 'info',
        children: 'This is a one-time message. Acknowledge it and move on with your life.',
        onClose: () => alert('👋'),
    },
}

export const Dismissable: Story = {
    render: Template,

    args: {
        type: 'info',
        children: 'If you dismiss this message, it will be gone forever. (Clear the localstorage key to get it back)',
        dismissKey: 'storybook-banner',
        onClose: () => alert('👋'),
    },
}
