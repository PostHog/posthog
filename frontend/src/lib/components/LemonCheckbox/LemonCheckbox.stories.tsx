import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonCheckbox, LemonCheckboxProps } from './LemonCheckbox'

export default {
    title: 'Components/Lemon Checkbox',
    component: LemonCheckbox,
} as ComponentMeta<typeof LemonCheckbox>

export function LemonCheckbox_(args: LemonCheckboxProps): JSX.Element {
    return <LemonCheckbox {...args} />
}
