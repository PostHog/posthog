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

const WideTemplate: StoryFn<typeof LemonBanner> = (props: LemonBannerProps) => {
    // We need to explicitly set size on the banner's parent, because LemonBanner is a CSS container
    // See: https://stackoverflow.com/a/73980194/3515268
    return (
        <div id="target" className="w-120">
            <LemonBanner {...props} />
        </div>
    )
}
WideTemplate.parameters = {
    testOptions: {
        snapshotTargetSelector: '#target',
    },
}

export const Info: Story = WideTemplate.bind({})
Info.args = { type: 'info', children: 'PSA: Every dish can be improved by adding more garlic.' }

export const Warning: Story = WideTemplate.bind({})
Warning.args = { type: 'warning', children: 'This spacecraft is about to explode. Please evacuate immediately.' }

export const Error: Story = WideTemplate.bind({})
Error.args = { type: 'error', children: 'This spacecraft has exploded. Too late...' }

export const Success: Story = WideTemplate.bind({})
Success.args = { type: 'success', children: 'This spacecraft has recovered. Phew!' }

export const Closable: Story = WideTemplate.bind({})
Closable.args = {
    type: 'info',
    children: 'This is a one-time message. Acknowledge it and move on with your life.',
    onClose: () => alert('👋'),
}

export const Dismissable: Story = WideTemplate.bind({})
Dismissable.args = {
    type: 'info',
    children: 'If you dismiss this message, it will be gone forever. (Clear the localstorage key to get it back)',
    dismissKey: 'storybook-banner',
    onClose: () => alert('👋'),
}

const NarrowTemplate: StoryFn<typeof LemonBanner> = (props: LemonBannerProps) => {
    // We need to explicitly set size on the banner's parent, because LemonBanner is a CSS container
    // See: https://stackoverflow.com/a/73980194/3515268
    return (
        <div id="target" className="w-50">
            <LemonBanner {...props} />
        </div>
    )
}
NarrowTemplate.parameters = {
    testOptions: {
        snapshotTargetSelector: '#target',
    },
}

export const Narrow: Story = NarrowTemplate.bind({})
Narrow.args = {
    type: 'info',
    children: 'This is a one-time message. Acknowledge it and move on with your life.',
}

export const NarrowWithButtons: Story = NarrowTemplate.bind({})
NarrowWithButtons.args = {
    type: 'info',
    children: 'This is a one-time message. Acknowledge it and move on with your life.',
    onClose: () => alert('👋'),
    action: {
        children: 'Acknowledge',
        onClick: () => alert('👋'),
    },
}
