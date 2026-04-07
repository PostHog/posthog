import type { Meta, StoryObj } from '@storybook/react-vite'

import { Button } from './button'
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
} from './select'

const meta = {
    title: 'Primitives/Select',
    component: Select,
    tags: ['autodocs'],
} satisfies Meta<typeof Select>

export default meta
type Story = StoryObj<typeof meta>

const fruits = [
    { label: 'Apple', value: 'apple' },
    { label: 'Banana', value: 'banana' },
    { label: 'Blueberry', value: 'blueberry' },
    { label: 'Grapes', value: 'grapes' },
    { label: 'Pineapple', value: 'pineapple' },
    { label: 'Watermelon', value: 'watermelon' },
    { label: 'Strawberry', value: 'strawberry' },
    { label: 'Orange', value: 'orange' },
    { label: 'Kiwi', value: 'kiwi' },
    { label: 'Mango', value: 'mango' },
    { label: 'Pear', value: 'pear' },
    { label: 'Peach', value: 'peach' },
    { label: 'Plum', value: 'plum' },
]
const vegetables = [
    { label: 'Carrot', value: 'carrot' },
    { label: 'Broccoli', value: 'broccoli' },
    { label: 'Spinach', value: 'spinach' },
    { label: 'Tomato', value: 'tomato' },
    { label: 'Potato', value: 'potato' },
    { label: 'Onion', value: 'onion' },
    { label: 'Garlic', value: 'garlic' },
    { label: 'Ginger', value: 'ginger' },
    { label: 'Pepper', value: 'pepper' },
    { label: 'Salt', value: 'salt' },
    { label: 'Sugar', value: 'sugar' },
]
const allItems = [{ label: 'Select a fruit', value: null }, ...fruits, ...vegetables]

export const Default: Story = {
    render: () => (
        <div className="max-w-48 mt-32">
            <Select items={allItems}>
                <SelectTrigger className="w-full max-w-48" render={<Button variant="outline" />}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectGroupLabel>Fruits</SelectGroupLabel>
                        {fruits.slice(0, 5).map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
    ),
} satisfies Story

export const GroupsAndSeparators: Story = {
    render: () => (
        <div className="max-w-48 mt-32">
            <Select items={allItems}>
                <SelectTrigger className="w-full max-w-48" render={<Button variant="outline" />}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectGroupLabel>Fruits</SelectGroupLabel>
                        {fruits.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                    <SelectSeparator />
                    <SelectGroup>
                        <SelectGroupLabel>Vegetables</SelectGroupLabel>
                        {vegetables.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
    ),
} satisfies Story

export const Disabled: Story = {
    render: () => (
        <div className="max-w-48 mt-32">
            <Select items={allItems}>
                <SelectTrigger className="w-full max-w-48" render={<Button variant="outline" disabled />}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectGroupLabel>Fruits</SelectGroupLabel>
                        {fruits.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                    <SelectSeparator />
                    <SelectGroup>
                        <SelectGroupLabel>Vegetables</SelectGroupLabel>
                        {vegetables.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
    ),
} satisfies Story
