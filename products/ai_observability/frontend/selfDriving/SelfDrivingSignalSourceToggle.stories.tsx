import type { Meta, StoryObj } from '@storybook/react'

import { SelfDrivingSignalSourceToggle, SelfDrivingSignalSourceToggleProps } from './SelfDrivingSignalSourceToggle'

const meta: Meta = {
    title: 'Scenes-App/AI observability/Self-driving signal source toggle',
}
export default meta

const render = (args: SelfDrivingSignalSourceToggleProps): JSX.Element => <SelfDrivingSignalSourceToggle {...args} />

const evalReportsArgs: SelfDrivingSignalSourceToggleProps = {
    sourceName: 'AI observability',
    signalNoun: 'evaluation report',
    enabled: true,
    loadFailed: false,
    toggling: false,
    onChange: () => {},
    onRetry: () => {},
    'data-attr': 'self-driving-signal-source-story',
}

export const On: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: evalReportsArgs,
}

export const Off: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: {
        ...evalReportsArgs,
        sourceName: 'Product analytics',
        signalNoun: 'anomaly investigation',
        enabled: false,
    },
}

export const Toggling: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: { ...evalReportsArgs, toggling: true },
    // The switch keeps a spinner while the write is in flight, which never settles in a story.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const Loading: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: { ...evalReportsArgs, enabled: null },
    // Same for the skeleton the switch shows until the signal source configs resolve.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const LoadFailed: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: { ...evalReportsArgs, enabled: null, loadFailed: true },
}
