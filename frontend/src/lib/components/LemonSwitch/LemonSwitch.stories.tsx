import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonSwitch, LemonSwitchProps } from './LemonSwitch'

export default {
    title: 'Lemon UI/Lemon Switch',
    component: LemonSwitch,
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
        label: {
            defaultValue: "Can't switch this!",
        },
    },
} as ComponentMeta<typeof LemonSwitch>

export function LemonSwitch_(props: LemonSwitchProps): JSX.Element {
    const [isChecked, setIsChecked] = useState(false)

    return (
        <LemonSwitch
            {...props}
            checked={props.checked !== undefined ? props.checked : isChecked}
            onChange={setIsChecked}
        />
    )
}
