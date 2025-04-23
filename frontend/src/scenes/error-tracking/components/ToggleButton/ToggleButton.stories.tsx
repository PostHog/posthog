import { IconBox } from '@posthog/icons'
import { Meta } from '@storybook/react'
import { useState } from 'react'

import { ToggleButtonPrimitive } from './ToggleButton'

const meta: Meta = {
    title: 'ErrorTracking/ToggleButton',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
}

export default meta

export function DefaultToggle(): JSX.Element {
    const [checked, setChecked] = useState(true)
    return (
        <ToggleButtonPrimitive tooltip="Toggle tooltip" checked={checked} onCheckedChange={setChecked}>
            <IconBox />
        </ToggleButtonPrimitive>
    )
}
