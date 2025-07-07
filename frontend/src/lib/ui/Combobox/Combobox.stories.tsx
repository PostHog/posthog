import type { Meta } from '@storybook/react'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { Combobox } from './Combobox'

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
                <Combobox.Search placeholder="Search this list..." />

                <Combobox.Empty>No results found</Combobox.Empty>

                {/* For styling the list items */}
                <Combobox.Content>
                    {/* responsible for filtering the list items */}
                    {/* can pass in an array of values to filter by */}
                    <Combobox.Group value={['Pineapple', 'belongs on pizza']}>
                        {/* what we actually get as focus */}
                        {/* eslint-disable-next-line no-console */}
                        <Combobox.Item asChild onClick={() => console.log('clicked Pineapple')}>
                            <ButtonPrimitive menuItem>Pineapple</ButtonPrimitive>
                        </Combobox.Item>
                    </Combobox.Group>

                    <Combobox.Group value={['Banana']}>
                        {/* eslint-disable-next-line no-console */}
                        <Combobox.Item asChild onClick={() => console.log('clicked Banana')}>
                            <ButtonPrimitive menuItem>Banana</ButtonPrimitive>
                        </Combobox.Item>
                    </Combobox.Group>
                </Combobox.Content>
            </Combobox>
        </div>
    )
}
