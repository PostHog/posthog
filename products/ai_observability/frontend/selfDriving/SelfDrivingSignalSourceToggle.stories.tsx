import type { Meta, StoryObj } from '@storybook/react'

import { SelfDrivingSignalSourceToggle, SelfDrivingSignalSourceToggleProps } from './SelfDrivingSignalSourceToggle'

const meta: Meta = {
    title: 'Scenes-App/AI observability/Self-driving signal source toggle',
}
export default meta

const render = (args: SelfDrivingSignalSourceToggleProps): JSX.Element => <SelfDrivingSignalSourceToggle {...args} />

export const On: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: {
        sourceName: 'AI observability',
        signalNoun: 'evaluation report',
        enabled: true,
        toggling: false,
        onChange: () => {},
        'data-attr': 'self-driving-signal-source-story',
    },
}

export const Off: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: {
        ...On.args,
        sourceName: 'Product analytics',
        signalNoun: 'anomaly investigation',
        enabled: false,
    } as SelfDrivingSignalSourceToggleProps,
}

export const Toggling: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: { ...On.args, toggling: true } as SelfDrivingSignalSourceToggleProps,
}

export const Loading: StoryObj<SelfDrivingSignalSourceToggleProps> = {
    render,
    args: { ...On.args, enabled: null } as SelfDrivingSignalSourceToggleProps,
}
