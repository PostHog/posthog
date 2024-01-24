import { Meta } from '@storybook/react'

import { LemonSlider } from './LemonSlider'

const meta: Meta<typeof LemonSlider> = {
    title: 'Lemon UI/Lemon Slider',
    component: LemonSlider,
    tags: ['autodocs'],
}
export default meta

export function Basic(): JSX.Element {
    return <LemonSlider value={53} min={0} max={100} step={1} />
}
