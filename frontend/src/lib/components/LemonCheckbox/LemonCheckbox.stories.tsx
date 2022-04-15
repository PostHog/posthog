import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonCheckbox, LemonCheckboxProps } from './LemonCheckbox'

export default {
    title: 'Lemon UI/Lemon Checkbox',
    component: LemonCheckbox,
} as ComponentMeta<typeof LemonCheckbox>

export function WithoutLabel(args: LemonCheckboxProps): JSX.Element {
    return <LemonCheckbox {...args} />
}

export function WithLabel(args: LemonCheckboxProps): JSX.Element {
    return <LemonCheckbox {...args} />
}
WithLabel.args = {
    label: 'Check this',
}
