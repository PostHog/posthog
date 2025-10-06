import type { Meta } from '@storybook/react'

import {
    SelectPrimitive,
    SelectPrimitiveContent,
    SelectPrimitiveGroup,
    SelectPrimitiveItem,
    SelectPrimitiveLabel,
    SelectPrimitiveSeparator,
    SelectPrimitiveTrigger,
    SelectPrimitiveValue,
} from './SelectPrimitive'

const meta = {
    title: 'UI/SelectPrimitive',
    component: SelectPrimitive as any,
    tags: ['autodocs'],
} satisfies Meta<typeof SelectPrimitive>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <SelectPrimitive>
                <SelectPrimitiveTrigger className="w-[180px]">
                    <SelectPrimitiveValue placeholder="Select a fruit" />
                </SelectPrimitiveTrigger>
                <SelectPrimitiveContent matchTriggerWidth>
                    <SelectPrimitiveGroup>
                        <SelectPrimitiveLabel>Fruits</SelectPrimitiveLabel>
                        <SelectPrimitiveSeparator />
                        <SelectPrimitiveItem value="apple">Apple</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="banana">Banana</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="blueberry">Blueberry</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="grapes">Grapes</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="pineapple">Pineapple</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="pear">Pear</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="orange">Orange</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="mango">Mango</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="kiwi">Kiwi</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="strawberry">Strawberry</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="watermelon">Watermelon</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="dragonfruit">Dragonfruit</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="1">1</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="2">2</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="3">3</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="4">4</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="5">5</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="6">6</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="7">7</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="8">8</SelectPrimitiveItem>
                        <SelectPrimitiveItem value="9">9</SelectPrimitiveItem>
                    </SelectPrimitiveGroup>
                </SelectPrimitiveContent>
            </SelectPrimitive>
        </div>
    )
}
