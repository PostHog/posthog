import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { PropertyKeyInfo } from './PropertyKeyInfo'

type Story = StoryObj<typeof PropertyKeyInfo>
const meta: Meta<typeof PropertyKeyInfo> = {
    title: 'Components/Property Key Info',
    component: PropertyKeyInfo,
}
export default meta

const Template: StoryFn<typeof PropertyKeyInfo> = (args) => {
    return args.value ? (
        <PropertyKeyInfo {...args} />
    ) : (
        <>
            <div>
                <PropertyKeyInfo {...args} value="$current_url" />
            </div>
            <div>
                <PropertyKeyInfo {...args} value="$feature/some-feature-key" />
            </div>
            <div>
                <PropertyKeyInfo {...args} value="$country" />
            </div>
            <div>
                <PropertyKeyInfo {...args} value="booking submitted" />
            </div>
        </>
    )
}

export const PropertyKeyInfo_: Story = Template.bind({})
PropertyKeyInfo_.args = {
    value: undefined,
    type: 'event',
    tooltipPlacement: undefined,
    disablePopover: false,
    disableIcon: false,
    ellipsis: true,
}
