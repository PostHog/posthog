import type { Meta, StoryObj } from '@storybook/react'

import { LemonBanner, LemonBannerProps } from './LemonBanner'

type Story = StoryObj<LemonBannerProps>
const meta: Meta<LemonBannerProps> = {
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

const renderWide = (props: LemonBannerProps): JSX.Element => {
    // We need to explicitly set size on the banner's parent, because LemonBanner is a CSS container
    // See: https://stackoverflow.com/a/73980194/3515268
    return (
        <div id="target" className="w-120">
            <LemonBanner {...props} />
        </div>
    )
}

const renderNarrow = (props: LemonBannerProps): JSX.Element => {
    // We need to explicitly set size on the banner's parent, because LemonBanner is a CSS container
    // See: https://stackoverflow.com/a/73980194/3515268
    return (
        <div id="target" className="w-50">
            <LemonBanner {...props} />
        </div>
    )
}

const renderSceneWidth = (props: LemonBannerProps): JSX.Element => {
    return (
        <div id="target" className="w-200">
            <LemonBanner {...props} />
        </div>
    )
}

const wideParameters = {
    testOptions: {
        snapshotTargetSelector: '#target',
    },
}

export const Info: Story = {
    render: renderWide,
    args: { type: 'info', children: 'PSA: Every dish can be improved by adding more butter.' },
    parameters: wideParameters,
}

export const Warning: Story = {
    render: renderWide,
    args: { type: 'warning', children: 'This spacecraft is about to explode. Please evacuate immediately.' },
    parameters: wideParameters,
}

export const Error: Story = {
    render: renderWide,
    args: { type: 'error', children: 'This spacecraft has exploded. Too late...' },
    parameters: wideParameters,
}

export const Success: Story = {
    render: renderWide,
    args: { type: 'success', children: 'This spacecraft has recovered. Phew!' },
    parameters: wideParameters,
}

export const AI: Story = {
    render: renderWide,
    args: {
        type: 'ai',
        children: 'Based on your goals, we recommend Product Analytics and Session Replay to understand user behavior.',
    },
    parameters: wideParameters,
}

export const Closable: Story = {
    render: renderWide,
    args: {
        type: 'info',
        children: 'This is a one-time message. Acknowledge it and move on with your life.',
        onClose: () => alert('👋'),
    },
    parameters: wideParameters,
}

export const Dismissable: Story = {
    render: renderWide,
    args: {
        type: 'info',
        children: 'If you dismiss this message, it will be gone forever. (Clear the localstorage key to get it back)',
        dismissKey: 'storybook-banner',
        onClose: () => alert('👋'),
    },
    parameters: wideParameters,
}

export const Narrow: Story = {
    render: renderNarrow,
    args: {
        type: 'info',
        children: 'This is a one-time message. Acknowledge it and move on with your life.',
    },
    parameters: wideParameters,
}

export const WarningWithAction: Story = {
    render: renderSceneWidth,
    args: {
        type: 'warning',
        children: (
            <div>
                <div className="font-semibold">Some filters are slowing down your queries</div>
                <div className="text-sm mt-0.5">
                    The following filters are not supported by the new query engine and are causing your queries to slow
                    down: <strong>$entry_referring_domain</strong>
                </div>
            </div>
        ),
        action: {
            children: 'Remove unsupported filters',
            onClick: () => alert('Filters removed'),
        },
    },
    parameters: wideParameters,
}

export const NarrowWithButtons: Story = {
    render: renderNarrow,
    args: {
        type: 'info',
        children: 'This is a one-time message. Acknowledge it and move on with your life.',
        onClose: () => alert('👋'),
        action: {
            children: 'Acknowledge',
            onClick: () => alert('👋'),
        },
    },
    parameters: wideParameters,
}
