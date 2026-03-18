import './SessionRecordingPreview.scss'

import { Meta, StoryFn } from '@storybook/react'

import { IconCursorClick, IconKeyboard } from '@posthog/icons'

import { PropertyIcons, PropertyIconsProps } from './SessionRecordingPreview'

const meta: Meta<typeof PropertyIcons> = {
    title: 'Replay/Components/PropertyIcons',
    component: PropertyIcons,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-31 12:00:00',
    },
}
export default meta

const Template: StoryFn<typeof PropertyIcons> = (args: PropertyIconsProps) => {
    return (
        <div className="border rounded px-4 py-2 w-fit">
            <PropertyIcons {...args} />
        </div>
    )
}

const webRecordingProperties = [
    { label: 'Mac OS X', value: 'Mac OS X', property: '$os' },
    { label: 'Chrome', value: 'Chrome', property: '$browser' },
    { label: 'United States', value: 'US', property: '$geoip_country_code' },
    { label: 'Desktop', value: 'Desktop', property: '$device_type' },
]

export const WebRecording = Template.bind({})
WebRecording.args = {
    loading: false,
    recordingProperties: webRecordingProperties,
}

export const AndroidRecording = Template.bind({})
AndroidRecording.args = {
    loading: false,
    recordingProperties: [
        { label: 'Android', value: 'Android', property: '$os_name' },
        { label: 'Awesome Fun App', value: 'Awesome Fun App', property: '$app_name' },
        { label: 'United States', value: 'US', property: '$geoip_country_code' },
        { label: 'Mobile', value: 'Mobile', property: '$device_type' },
    ],
}

export const Loading = Template.bind({})
Loading.args = {
    loading: true,
    recordingProperties: [],
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

const iconClassNames = 'text-secondary shrink-0'

const ActivityCounts = (): JSX.Element => (
    <div className="flex gap-1">
        <span className="flex gap-x-0.5">
            <IconCursorClick className={iconClassNames} />
            <span>42</span>
            <span className="SessionRecordingPreview__activity-label text-secondary">clicks</span>
        </span>
        <span className="flex gap-x-0.5">
            <IconKeyboard className={iconClassNames} />
            <span>18</span>
            <span className="SessionRecordingPreview__activity-label text-secondary">keys</span>
        </span>
    </div>
)

export const NarrowWidth: StoryFn<typeof PropertyIcons> = () => {
    return (
        <div className="SessionRecordingPreview border rounded px-4 py-2" style={{ width: '200px' }}>
            <div className="flex gap-x-4 text-secondary text-sm">
                <PropertyIcons loading={false} recordingProperties={webRecordingProperties} />
                <ActivityCounts />
            </div>
        </div>
    )
}
NarrowWidth.parameters = {
    docs: {
        description: {
            story: 'At narrow widths (< 30rem), property and activity labels are hidden.',
        },
    },
}

export const MediumWidth: StoryFn<typeof PropertyIcons> = () => {
    return (
        <div className="SessionRecordingPreview border rounded px-4 py-2" style={{ width: '30rem' }}>
            <div className="flex gap-x-4 text-secondary text-sm">
                <PropertyIcons loading={false} recordingProperties={webRecordingProperties} />
                <ActivityCounts />
            </div>
        </div>
    )
}
MediumWidth.parameters = {
    docs: {
        description: {
            story: 'At medium widths (>= 30rem), property labels become visible.',
        },
    },
}

export const WideWidth: StoryFn<typeof PropertyIcons> = () => {
    return (
        <div className="SessionRecordingPreview border rounded px-4 py-2" style={{ width: '40rem' }}>
            <div className="flex gap-x-4 text-secondary text-sm">
                <PropertyIcons loading={false} recordingProperties={webRecordingProperties} />
                <ActivityCounts />
            </div>
        </div>
    )
}
WideWidth.parameters = {
    docs: {
        description: {
            story: 'At wide widths (>= 35rem), both property and activity labels are visible.',
        },
    },
}
