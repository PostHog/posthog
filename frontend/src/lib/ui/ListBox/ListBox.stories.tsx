import { Link } from '@posthog/lemon-ui'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useState } from 'react'

import { ButtonPrimitive } from '../Button/ButtonPrimitives'
import { ListBox } from './ListBox'

type Story = StoryObj<typeof ListBox>
const meta: Meta<typeof ListBox> = {
    title: 'UI/List Box',
    component: ListBox,
    args: {},
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof ListBox> = (props: React.ComponentProps<typeof ListBox>) => {
    const [expandedItemIds, setExpandedItemIds] = useState<string[]>([])

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <p className="m-0">ListBox</p>
                <p>
                    all elements inside (button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])) gain
                    focus when clicked or focused with keyboard.
                </p>
            </div>
            <ListBox
                className="flex flex-col gap-px max-h-[400px] overflow-y-auto border-1 border-dashed border-darkgray p-2"
                {...props}
            >
                <ListBox.Item asChild className="mb-4">
                    <LemonInput
                        fullWidth
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    />
                </ListBox.Item>
                <ListBox.Item asChild>
                    <Link
                        to="https://www.google.com"
                        target="_blank"
                        buttonProps={{
                            menuItem: true,
                        }}
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 1 (Link)
                    </Link>
                </ListBox.Item>
                <ListBox.Item asChild onClick={() => alert('clicked')}>
                    <ButtonPrimitive
                        menuItem
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 2 (Clickable)
                    </ButtonPrimitive>
                </ListBox.Item>
                <ListBox.Item asChild aria-disabled>
                    <ButtonPrimitive
                        menuItem
                        disabled
                        className="data-[focused=true]:bg-fill-button-tertiary-active aria-[current=true]:bg-fill-button-tertiary-active"
                    >
                        Option 3
                    </ButtonPrimitive>
                </ListBox.Item>
                <AccordionPrimitive.Root
                    type="multiple"
                    value={expandedItemIds}
                    onValueChange={(s) => {
                        setExpandedItemIds(s)
                    }}
                    defaultValue={['one']}
                >
                    <AccordionPrimitive.Item value="one" className="flex flex-col w-full">
                        <AccordionPrimitive.Trigger className="flex items-center gap-2 w-full h-8" asChild>
                            <ListBox.Item asChild>
                                <ButtonPrimitive menuItem fullWidth>
                                    Option 3 (Accordion)
                                </ButtonPrimitive>
                            </ListBox.Item>
                        </AccordionPrimitive.Trigger>
                        <AccordionPrimitive.Content className="ml-4">
                            <ListBox.Item asChild>
                                <ButtonPrimitive menuItem fullWidth>
                                    Option 3 child
                                </ButtonPrimitive>
                            </ListBox.Item>
                        </AccordionPrimitive.Content>
                    </AccordionPrimitive.Item>
                </AccordionPrimitive.Root>

                <ListBox.Item asChild>
                    <ButtonPrimitive fullWidth menuItem>
                        Option 4
                    </ButtonPrimitive>
                </ListBox.Item>
            </ListBox>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const VirtualFocus: Story = BasicTemplate.bind({})
VirtualFocus.args = {
    virtualFocus: true,
}
