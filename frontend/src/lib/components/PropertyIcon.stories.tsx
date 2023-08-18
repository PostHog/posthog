import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { PROPERTIES_ICON_MAP, PropertyIcon } from 'lib/components/PropertyIcon'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { countryCodeToName } from 'scenes/insights/views/WorldMap'

type Story = StoryObj<typeof PropertyIcon>
const meta: Meta<typeof PropertyIcon> = {
    title: 'Lemon UI/Icons/Property Icon',
    component: PropertyIcon,
    parameters: {
        testOptions: { skip: true }, // There are too many icons, the snapshots are huge in table form
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof PropertyIcon> = (args) => {
    if (args.value) {
        return <PropertyIcon {...args} />
    }

    const data = [
        ...Object.keys(
            args.property === '$geoip_country_code' ? countryCodeToName : PROPERTIES_ICON_MAP[args.property]
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
                ]}
            />
        </>
    )
}

export const Default_: Story = {
    render: Template,

    args: {
        property: '$browser',
        value: 'Chrome',
    },
}

export const Browser_: Story = {
    render: Template,

    args: {
        property: '$browser',
    },
}

export const DeviceType_: Story = {
    render: Template,

    args: {
        property: '$device_type',
    },
}

export const OS_: Story = {
    render: Template,

    args: {
        property: '$os',
    },
}

export const Country_: Story = {
    render: Template,

    args: {
        property: '$geoip_country_code',
    },
}
