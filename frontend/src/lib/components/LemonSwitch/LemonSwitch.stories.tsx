import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonSwitch as _LemonSwitch } from './LemonSwitch'

export default {
    title: 'PostHog/Components/LemonSwitch',
    component: _LemonSwitch,
    parameters: { options: { showPanel: true } },
} as ComponentMeta<typeof _LemonSwitch>

export function LemonSwitch(): JSX.Element {
    const [isChecked, setIsChecked] = useState(false)

    return <_LemonSwitch checked={isChecked} onChange={setIsChecked} />
}
