import { Meta } from '@storybook/react'

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

const Template = (args: PropertyIconsProps): JSX.Element => {
    return (
        <div className={'border rounded px-4 py-2 w-fit'}>
            <PropertyIcons {...args} />
        </div>
    )
}

export const WebRecording = (): JSX.Element => {
    return (
        <Template
            iconClassnames={'wat'}
            loading={false}
            onPropertyClick={() => {}}
            recordingProperties={[
                { value: 'Mac OS X', property: '$os', tooltipValue: 'Mac OS X' },
                { value: 'Chrome', property: '$browser', tooltipValue: 'Chrome' },
                { value: 'United States', property: '$geoip_country_code', tooltipValue: 'United States' },
                { value: 'Desktop', property: '$device_type', tooltipValue: 'Desktop' },
            ]}
        />
    )
}

export const AndroidRecording = (): JSX.Element => {
    return (
        <Template
            iconClassnames={'wat'}
            loading={false}
            onPropertyClick={() => {}}
            recordingProperties={[
                { value: 'Android', property: '$os_name', tooltipValue: 'Android' },
                { value: 'Awesome Fun App', property: '$app_name', tooltipValue: 'Awesome Fun App' },
                { value: 'United States', property: '$geoip_country_code', tooltipValue: 'United States' },
                { value: 'Mobile', property: '$device_type', tooltipValue: 'Mobile' },
            ]}
        />
    )
}

export const Loading = (): JSX.Element => {
    return <Template iconClassnames={'wat'} loading={true} onPropertyClick={() => {}} recordingProperties={[]} />
}
