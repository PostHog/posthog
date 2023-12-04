import { Meta, StoryFn } from '@storybook/react'

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
        <div className={'border rounded px-4 py-2 w-fit'}>
            <PropertyIcons {...args} />
        </div>
    )
}

export const WebRecording = Template.bind({})
WebRecording.args = {
    iconClassnames: 'wat',
    loading: false,
    onPropertyClick: () => {},
    recordingProperties: [
        { value: 'Mac OS X', property: '$os', tooltipValue: 'Mac OS X' },
        { value: 'Chrome', property: '$browser', tooltipValue: 'Chrome' },
        { value: 'United States', property: '$geoip_country_code', tooltipValue: 'United States' },
        { value: 'Desktop', property: '$device_type', tooltipValue: 'Desktop' },
    ],
}

export const AndroidRecording = Template.bind({})
AndroidRecording.args = {
    iconClassnames: 'wat',
    loading: false,
    onPropertyClick: () => {},
    recordingProperties: [
        { value: 'Android', property: '$os_name', tooltipValue: 'Android' },
        { value: 'Awesome Fun App', property: '$app_name', tooltipValue: 'Awesome Fun App' },
        { value: 'United States', property: '$geoip_country_code', tooltipValue: 'United States' },
        { value: 'Mobile', property: '$device_type', tooltipValue: 'Mobile' },
    ],
}

export const Loading = Template.bind({})
Loading.args = {
    iconClassnames: 'wat',
    loading: true,
    onPropertyClick: () => {},
    recordingProperties: [],
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}
