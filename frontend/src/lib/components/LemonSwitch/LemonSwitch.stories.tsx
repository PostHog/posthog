import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonSwitch } from './LemonSwitch'

export default {
    title: 'DataDisplay',
    component: LemonSwitch,
    parameters: { options: { showPanel: true } },
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
    },
} as ComponentMeta<typeof LemonSwitch>

export function LemonSwitch_({ loading }: { loading: boolean }): JSX.Element {
    const [isChecked, setIsChecked] = useState(false)

    return <LemonSwitch loading={loading} checked={isChecked} onChange={setIsChecked} />
}
