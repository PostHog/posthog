import type { Meta, StoryObj } from '@storybook/react'

import { PROPERTIES_ICON_MAP, PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { PropertyIconProps } from 'lib/components/PropertyIcon/types'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/geography/country'

type Story = StoryObj<PropertyIconProps>
const meta: Meta<PropertyIconProps> = {
    title: 'Lemon UI/Icons/Property Icon',
    component: PropertyIcon,
    tags: ['autodocs', 'test-skip'], // There are too many icons, the snapshots are huge in table form
    render: (args) => {
        if (args.value) {
            return <PropertyIcon {...args} />
        }

        const data = [
            ...Object.keys(
                args.property === '$geoip_country_code' ? COUNTRY_CODE_TO_LONG_NAME : PROPERTIES_ICON_MAP[args.property]
            ).map((value) => ({ value })),
            { value: '(unknown value)' },
            { value: undefined },
        ]

        return (
            <>
                <code className="font-bold">{args.property}</code>
                <LemonTable
                    className="mt-4"
                    dataSource={data}
                    columns={[
                        {
                            title: 'Value',
                            key: 'value',
                            dataIndex: 'value',
                            render: function RenderValue(value) {
                                return <code>{value as string}</code>
                            },
                        },
                        {
                            title: 'Icon',
                            key: 'icon',
                            render: function RenderIcon(_, { value }) {
                                return <PropertyIcon property={args.property} value={value} />
                            },
                        },
                        {
                            title: 'With Label',
                            key: 'withLabel',
                            render: function RenderWithLabel(_, { value }) {
                                return <PropertyIcon.WithLabel property={args.property} value={value} />
                            },
                        },
                    ]}
                />
            </>
        )
    },
}
export default meta

export const Default_: Story = {
    args: {
        property: '$browser',
        value: 'Chrome',
    },
}

export const Browser_: Story = {
    args: {
        property: '$browser',
    },
}

export const DeviceType_: Story = {
    args: {
        property: '$device_type',
    },
}

export const OS_: Story = {
    args: {
        property: '$os',
    },
}

export const Country_: Story = {
    args: {
        property: '$geoip_country_code',
    },
}

export const FaviconSizeComparison: Story = {
    tags: ['autodocs'],
    render: () => {
        const domains = ['www.facebook.com', 'www.google.com', 'github.com']
        return (
            <div className="space-y-4">
                <h3>Favicon size should match PropertyIcon (both use 1em)</h3>
                <div className="space-y-2">
                    {domains.map((domain) => (
                        <div key={domain} className="flex items-center gap-4">
                            <div className="flex items-center gap-2">
                                <img
                                    src={`https://app-static-prod.posthog.com/favicons/${domain}`}
                                    className="size-[1em]"
                                    alt={`${domain} favicon`}
                                />
                                <span>{domain}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <PropertyIcon.WithLabel property="$browser" value="Chrome" />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        )
    },
}
