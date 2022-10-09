import { ComponentMeta, ComponentStory } from '@storybook/react'
import React from 'react'
import { CurrencyPicker } from 'lib/components/CurrencyPicker/CurrencyPicker'

export default {
    title: 'Components/Currency Picker',
    component: CurrencyPicker,
} as ComponentMeta<typeof CurrencyPicker>

export const Default: ComponentStory<typeof CurrencyPicker> = () => {
    return <CurrencyPicker />
}
