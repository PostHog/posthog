import { Meta } from '@storybook/react'
import { useState } from 'react'

import { LemonSlider } from './LemonSlider'

const meta: Meta<typeof LemonSlider> = {
    title: 'Lemon UI/Lemon Slider',
    component: LemonSlider,
    tags: ['autodocs'],
}
export default meta

export function Basic(): JSX.Element {
    const [value, setValue] = useState(42)

    return (
        <>
            <LemonSlider value={value} min={0} max={100} step={1} onChange={setValue} />
            <LemonSlider value={NaN} min={0} max={100} step={1} onChange={setValue} />
            {/* Values outside the min,max range are clamped */}
            <LemonSlider value={3000} min={0} max={100} step={1} onChange={setValue} />
            <LemonSlider value={-3000} min={0} max={100} step={1} onChange={setValue} />
        </>
    )
}
