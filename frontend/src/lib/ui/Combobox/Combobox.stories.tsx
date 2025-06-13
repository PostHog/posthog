import type { Meta } from '@storybook/react'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { Combobox, ComboboxContent, ComboboxItem, ComboboxSearch } from './Combobox'

const meta = {
    title: 'UI/Combobox',
    component: Combobox,
    tags: ['autodocs'],
} satisfies Meta<typeof Combobox>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex gap-4">
            <Combobox>
                <ComboboxSearch placeholder="Search this list..." />

                <ComboboxContent>
                    <ComboboxItem asChild onClick={() => console.log('clicked Pineapple')}>
                        <ButtonPrimitive menuItem>Pineapple</ButtonPrimitive>
                    </ComboboxItem>

                    <ComboboxItem asChild onClick={() => console.log('clicked Banana')}>
                        <ButtonPrimitive menuItem>Banana</ButtonPrimitive>
                    </ComboboxItem>
                </ComboboxContent>
            </Combobox>
        </div>
    )
}
