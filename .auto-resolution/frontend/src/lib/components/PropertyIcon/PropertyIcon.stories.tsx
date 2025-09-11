import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { PROPERTIES_ICON_MAP, PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/geography/country'

type Story = StoryObj<typeof PropertyIcon>
const meta: Meta<typeof PropertyIcon> = {
    title: 'Lemon UI/Icons/Property Icon',
    component: PropertyIcon,
    tags: ['autodocs', 'test-skip'], // There are too many icons, the snapshots are huge in table form
}
export default meta

const Template: StoryFn<typeof PropertyIcon> = (args) => {
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
}

export const Default_: Story = Template.bind({})
Default_.args = {
    property: '$browser',
    value: 'Chrome',
}

export const Browser_: Story = Template.bind({})
Browser_.args = {
    property: '$browser',
}

export const DeviceType_: Story = Template.bind({})
DeviceType_.args = {
    property: '$device_type',
}

export const OS_: Story = Template.bind({})
OS_.args = {
    property: '$os',
}

export const Country_: Story = Template.bind({})
Country_.args = {
    property: '$geoip_country_code',
}
