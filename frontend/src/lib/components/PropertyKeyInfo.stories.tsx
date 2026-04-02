import type { Meta, StoryObj } from '@storybook/react'

import { PropertyKeyInfo, PropertyKeyInfoProps } from './PropertyKeyInfo'
import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

type Story = StoryObj<PropertyKeyInfoProps>
const meta: Meta<PropertyKeyInfoProps> = {
    title: 'Components/Property Key Info',
    component: PropertyKeyInfo as any,
    render: (args) => {
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
                    <PropertyKeyInfo {...args} value="langfuse trace" />
                </div>
                <div>
                    <PropertyKeyInfo {...args} value="$country" />
                </div>
                <div>
                    <PropertyKeyInfo {...args} value="booking submitted" />
                </div>
            </>
        )
    },
}
export default meta

export const PropertyKeyInfo_: Story = {
    args: {
        value: undefined,
        type: TaxonomicFilterGroupType.EventProperties,
        tooltipPlacement: undefined,
        disablePopover: false,
        disableIcon: false,
        ellipsis: true,
    },
}
