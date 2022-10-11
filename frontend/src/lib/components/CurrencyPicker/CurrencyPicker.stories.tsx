import { ComponentMeta, ComponentStory } from '@storybook/react'
import React, { useState } from 'react'
import { currencies, CurrencyPicker } from 'lib/components/CurrencyPicker/CurrencyPicker'

export default {
    title: 'Components/Currency Picker',
    component: CurrencyPicker,
} as ComponentMeta<typeof CurrencyPicker>

export const Default: ComponentStory<typeof CurrencyPicker> = () => {
    const [value, setValue] = useState<currencies>([] as unknown as currencies)
    return <CurrencyPicker value={value} onChange={(changed) => setValue(changed)} />
}
